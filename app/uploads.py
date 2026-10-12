"""Temporary file store for photos/videos/documents before sending (lives 1 hour).

Three ways to get a file here:
- upload link: a page (phone) or `curl -F file=@x.jpg <link>` (Claude Code);
- ChatGPT attachments (openai/fileParams): ChatGPT passes signed download URLs;
- a public https URL.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import re
import secrets
import shutil
import socket
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import config
from .oauth import page
from .signing import sign, verify

TTL = 3600
MAX_BYTES = 20 * 1024 * 1024
MAX_FILES = 10
ROOT = Path(tempfile.gettempdir()) / "tg-ai-uploads"
_store: dict[str, dict] = {}

SIGNATURES = {
    "jpg": lambda h: h.startswith(b"\xff\xd8\xff"),
    "png": lambda h: h.startswith(b"\x89PNG\r\n\x1a\n"),
    "webp": lambda h: h.startswith(b"RIFF") and h[8:12] == b"WEBP",
    "gif": lambda h: h.startswith((b"GIF87a", b"GIF89a")),
    "mp4": lambda h: h[4:8] == b"ftyp",
}
PHOTO_KINDS = {"jpg", "png", "webp"}


def detect(head: bytes) -> str:
    for kind, check in SIGNATURES.items():
        if check(head):
            return kind
    return "file"


def _cleanup() -> None:
    now = time.time()
    for upload_id, item in list(_store.items()):
        if now - item["created"] > TTL:
            shutil.rmtree(Path(item["path"]).parent, ignore_errors=True)
            _store.pop(upload_id, None)


def save_bytes(name: str, data: bytes, source: str) -> dict:
    _cleanup()
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError("Файл должен быть от 1 байта до 20 МБ")
    safe = re.sub(r"[^\w.\-]", "_", Path(name or "file").name)[:80] or "file"
    upload_id = "u" + secrets.token_hex(6)
    folder = ROOT / upload_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe
    path.write_bytes(data)
    item = {"id": upload_id, "name": safe, "size": len(data), "kind": detect(data[:16]),
            "sha256": hashlib.sha256(data).hexdigest(), "source": source,
            "created": time.time(), "path": str(path)}
    _store[upload_id] = item
    return public(item)


def public(item: dict) -> dict:
    return {k: item[k] for k in ("id", "name", "size", "kind", "source")}


def get(upload_ids: list[str]) -> list[dict]:
    _cleanup()
    if len(upload_ids) > MAX_FILES:
        raise ValueError(f"Не больше {MAX_FILES} файлов за раз")
    missing = [u for u in upload_ids if u not in _store]
    if missing:
        raise ValueError(f"Файлы не найдены или устарели (живут 1 час): {', '.join(missing)}")
    return [_store[u] for u in upload_ids]


def recent(limit: int = 20) -> list[dict]:
    _cleanup()
    items = sorted(_store.values(), key=lambda i: i["created"], reverse=True)
    return [public(i) for i in items[:limit]]


# ---------------------------------------------------------------- upload link
def new_link() -> str:
    return f"{config.PUBLIC_URL}/upload?t={sign('upload', {}, TTL)}"


async def upload_page(request: Request):
    if not verify("upload", request.query_params.get("t", "")):
        return page("Ссылка устарела", "<p>Попросите ИИ дать новую ссылку загрузки.</p>")
    return page("Загрузка файлов", """<p>Выберите фото, видео или файлы (до 10 штук, до 20 МБ каждый).</p>
<input id="f" type="file" multiple><button id="b">Загрузить</button><p id="s" class="muted"></p>
<script>
b.onclick = async () => {
  const fd = new FormData(); for (const x of f.files) fd.append("file", x);
  if (!f.files.length) { s.textContent = "Сначала выберите файлы"; return; }
  s.textContent = "Загружаю...";
  const r = await fetch(location.href, {method: "POST", body: fd});
  const j = await r.json();
  s.innerHTML = r.ok ? "Готово! Вернитесь в чат и напишите ИИ: «загрузил». ID: " + j.uploads.map(u => u.id).join(", ")
                     : "Ошибка: " + j.error;
};
</script>""")


async def upload_submit(request: Request):
    if not verify("upload", request.query_params.get("t", "")):
        return JSONResponse({"error": "Ссылка устарела"}, status_code=403)
    form = await request.form(max_files=MAX_FILES, max_part_size=MAX_BYTES)
    results = []
    try:
        for part in form.getlist("file"):
            if hasattr(part, "read"):
                results.append(save_bytes(part.filename, await part.read(), "upload"))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if not results:
        return JSONResponse({"error": "Нет файлов в поле file"}, status_code=400)
    return JSONResponse({"uploads": results})


# ---------------------------------------------------------------- download by URL
def _openai_host(host: str) -> bool:
    # ChatGPT attachment storage (from the original bridge allowlist).
    return bool(re.fullmatch(r"(?:oaisdmntpr[a-z0-9-]*|oaisdsorpr[a-z0-9-]*)\.blob\.core\.windows\.net", host)
                or re.fullmatch(r"sdmntpr[a-z0-9-]*\.oaiusercontent\.com", host))


async def _public_ip(host: str) -> bool:
    infos = await asyncio.to_thread(socket.getaddrinfo, host, 443)
    return all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


async def download(url: str, name: str = "", source: str = "url") -> dict:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.port not in (None, 443):
        raise ValueError("Нужна обычная https-ссылка")
    if not await _public_ip(host):
        raise ValueError("Адрес ведёт во внутреннюю сеть, отклонено")
    async with httpx.AsyncClient(follow_redirects=False, timeout=45, trust_env=False) as client:
        async with client.stream("GET", url) as response:
            if response.is_redirect:
                raise ValueError("Ссылка делает редирект; дайте прямую ссылку на файл")
            response.raise_for_status()
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("Файл больше 20 МБ")
                chunks.append(chunk)
    filename = name or Path(parsed.path).name or "file"
    return save_bytes(filename, b"".join(chunks), source)


async def download_chatgpt(url: str, name: str) -> dict:
    host = (urlparse(url).hostname or "").lower()
    if not _openai_host(host):
        raise ValueError(f"Неизвестный хост вложения ChatGPT: {host}")
    return await download(url, name, "chatgpt")
