"""Whole-chat export, ported from ord-tg-bridge: compact day-grouped text in parts (kept 1 hour)."""
from __future__ import annotations

import re
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from starlette.requests import Request
from starlette.responses import PlainTextResponse

from . import config
from .signing import sign, verify
from .tg import _dialog, _name, client, kind_of, msk

EXPORT_TTL = 3600
MAX_EXPORTS = 20
CHARS_PER_TOKEN = 3  # rough figure for Russian text
EXPORTS: dict[str, dict] = {}
KIND_LABELS = {"photo": "фото", "video": "видео", "voice": "голосовое", "audio": "аудио",
               "file": "файл", "gif": "gif", "round_video": "кружок", "sticker": "стикер"}


def _tz() -> ZoneInfo:
    return ZoneInfo(config.TIMEZONE)


def _day_bounds(value: str) -> tuple[datetime, datetime]:
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Дата в формате YYYY-MM-DD") from exc
    start = datetime(day.year, day.month, day.day, tzinfo=_tz())
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def _moment(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("after: дата-время ISO, например 2026-09-12T14:03:00+03:00") from exc
    return (moment if moment.tzinfo else moment.replace(tzinfo=_tz())).astimezone(timezone.utc)


def format_message(m, names: dict, with_ids: bool = False) -> str | None:
    """'14:03 Настя: текст [фото] [файл: a.xlsx]'; None for empty service messages."""
    kind = kind_of(m)
    text = (m.message or "").strip()
    if not text and kind == "text":
        return None
    sender = getattr(m, "sender", None)
    who = "Я" if m.out else (names.get(m.sender_id) or (_name(sender) if sender else str(m.sender_id)))
    if not m.out:
        names[m.sender_id] = who
    parts = [re.sub(r"\s*\n\s*", " ⏎ ", text)] if text else []
    if kind != "text":
        label = KIND_LABELS.get(kind, kind)
        fname = getattr(getattr(m, "file", None), "name", None)
        parts.append(f"[{label}: {fname}]" if fname and kind == "file" else f"[{label}]")
    prefix = m.date.astimezone(_tz()).strftime("%H:%M")
    if with_ids:
        prefix += f" #{m.id}"
        reply = getattr(m, "reply_to", None)
        if reply and getattr(reply, "reply_to_msg_id", None):
            prefix += f" ↩#{reply.reply_to_msg_id}"
    return f"{prefix} {who}: {' '.join(parts)}"


def _purge(now: float) -> None:
    for key in [k for k, v in EXPORTS.items() if v["expires"] < now]:
        del EXPORTS[key]
    while len(EXPORTS) >= MAX_EXPORTS:
        del EXPORTS[min(EXPORTS, key=lambda k: EXPORTS[k]["expires"])]


async def export_chat(dialog_id: int, date_from: str = "", date_to: str = "", after: str = "",
                      sender_id: int = 0, with_ids: bool = False, chunk_tokens: int = 25000,
                      max_messages: int = 30000, time_budget_s: int = 40) -> dict:
    if not (2000 <= chunk_tokens <= 100000 and 1 <= max_messages <= 50000 and 5 <= time_budget_s <= 90):
        raise ValueError("chunk_tokens 2000-100000, max_messages 1-50000, time_budget_s 5-90")
    start = _day_bounds(date_from)[0] if date_from else None
    end = _day_bounds(date_to)[1] if date_to else None
    if after:  # continue an unfinished export
        moment = _moment(after)
        start = moment if start is None else max(start, moment)

    chunk_chars = chunk_tokens * CHARS_PER_TOKEN
    parts: list[list[str]] = [[]]
    sizes = [0]
    names: dict = {}
    count, first_date, last_date, current_day, complete = 0, None, None, None, True
    deadline = time.monotonic() + time_budget_s

    async with client() as c:
        d = await _dialog(c, dialog_id)
        # With reverse=True offset_date means "newer than" (exclusive).
        offset = (start - timedelta(seconds=1)) if start else None
        async for m in c.iter_messages(d.input_entity, reverse=True, offset_date=offset,
                                       limit=None, wait_time=0):
            when = m.date.astimezone(timezone.utc)
            if end and when >= end:
                break
            if sender_id and m.sender_id != sender_id:
                continue
            line = format_message(m, names, with_ids)
            if line is None:
                continue
            day = m.date.astimezone(_tz()).strftime("%d.%m.%Y")
            need_header = day != current_day
            current_day = day
            if sizes[-1] and sizes[-1] + len(line) > chunk_chars:
                parts.append([])  # every part starts with its own date header
                sizes.append(0)
                need_header = True
            if need_header:
                line = f"=== {day} ===\n{line}"
            parts[-1].append(line)
            sizes[-1] += len(line) + 1
            count += 1
            first_date = first_date or m.date
            last_date = m.date
            if count >= max_messages or time.monotonic() > deadline:
                complete = False
                break

    now = time.time()
    _purge(now)
    export_id = secrets.token_urlsafe(9)
    texts = ["\n".join(p) for p in parts if p]
    EXPORTS[export_id] = {"parts": texts, "expires": now + EXPORT_TTL, "chat": d.name}
    return {
        "export_id": export_id, "chat": d.name, "messages": count,
        "approx_tokens": sum(len(t) for t in texts) // CHARS_PER_TOKEN,
        "first_date": msk(first_date) if first_date else None,
        "last_date": msk(last_date) if last_date else None,
        "complete": complete,
        "resume_after": last_date.astimezone(_tz()).isoformat() if (last_date and not complete) else None,
        "parts": [{"part": i + 1, "approx_tokens": len(t) // CHARS_PER_TOKEN,
                   "download_url": f"{config.PUBLIC_URL}/export.txt?t="
                                   + sign("export", {"id": export_id, "p": i + 1}, EXPORT_TTL)}
                  for i, t in enumerate(texts)],
        "expires_in_s": EXPORT_TTL,
    }


def get_part(export_id: str, part: int = 1) -> dict:
    entry = EXPORTS.get(export_id)
    if not entry or entry["expires"] < time.time():
        raise ValueError("Экспорт не найден или устарел (живёт 1 час) — запусти export_chat снова")
    if not 1 <= part <= len(entry["parts"]):
        raise ValueError(f"part должен быть 1-{len(entry['parts'])}")
    return {"export_id": export_id, "chat": entry["chat"], "part": part, "of": len(entry["parts"]),
            "text": entry["parts"][part - 1]}


async def download(request: Request):
    data = verify("export", request.query_params.get("t", ""))
    if not data:
        return PlainTextResponse("Ссылка устарела", status_code=403)
    try:
        part = get_part(data["id"], int(data["p"]))
    except ValueError as exc:
        return PlainTextResponse(str(exc), status_code=404)
    name = f"chat-export-part{part['part']}.txt"
    return PlainTextResponse(part["text"], headers={"Content-Disposition": f'attachment; filename="{name}"'})
