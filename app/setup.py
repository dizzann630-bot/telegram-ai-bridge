"""/setup: log the owner's Telegram account in by QR code, in the browser.

The result is a session string that the owner pastes into the Render secret
TELEGRAM_SESSION. It never goes through the AI chat.
"""
from __future__ import annotations

import asyncio
import base64
import io
import secrets
import time

import qrcode
from starlette.requests import Request
from starlette.responses import JSONResponse
from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError

from . import config, guides
from .oauth import guard, page
from .signing import sign, verify
from .tg import TelegramError, new_client

_pending: dict[str, dict] = {}
LIFETIME = 900


def _qr_png(url: str) -> str:
    buf = io.BytesIO()
    qrcode.make(url, border=2).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _cleanup() -> None:
    now = time.time()
    for pid, item in list(_pending.items()):
        if now - item["created"] > LIFETIME:
            _pending.pop(pid, None)
            asyncio.create_task(item["client"].disconnect())


async def _wait(pid: str) -> None:
    item = _pending[pid]
    while time.time() - item["created"] < LIFETIME:
        try:
            await item["qr"].wait(timeout=30)
            await _finish(item)
            return
        except asyncio.TimeoutError:
            await item["qr"].recreate()
        except SessionPasswordNeededError:
            item["status"] = "need_2fa"
            return
        except Exception as exc:  # network trouble, revoked token, etc.
            item.update(status="error", error=type(exc).__name__)
            return
    item["status"] = "expired"


async def _finish(item: dict) -> None:
    me = await item["client"].get_me()
    item.update(status="ok", name=" ".join(x for x in (me.first_name, me.last_name) if x),
                session=item["client"].session.save())
    await item["client"].disconnect()


async def setup_page(request: Request):
    if not config.TELEGRAM_API_ID or not config.TELEGRAM_API_HASH:
        return page("Подключение Telegram", "<p class='err'>Сначала задайте TELEGRAM_API_ID и "
                    "TELEGRAM_API_HASH в настройках Render (Environment).</p>")
    return page("Подключение Telegram", """<p>Введите пароль сервера (ADMIN_PASSWORD), затем
отсканируйте QR телефоном.</p><form method="post"><input type="password" name="password"
placeholder="Пароль сервера" required autofocus><button>Показать QR</button></form>""")


async def setup_submit(request: Request):
    form = await request.form()
    error = await guard.check(str(form.get("password", "")))
    if error:
        return page("Подключение Telegram", f"<p class='err'>{error}</p><a href='/setup'>Назад</a>")
    _cleanup()
    client = new_client()
    try:
        await asyncio.wait_for(client.connect(), 30)
        qr = await client.qr_login()
    except (asyncio.TimeoutError, OSError, TelegramError) as exc:
        return page("Подключение Telegram", f"<p class='err'>Не удалось связаться с Telegram: {exc}</p>")
    pid = secrets.token_hex(8)
    _pending[pid] = {"client": client, "qr": qr, "status": "pending", "created": time.time()}
    asyncio.create_task(_wait(pid))
    key = sign("setup", {"id": pid}, LIFETIME)
    return page("Подключение Telegram", f"""
<p>На телефоне: <b>Telegram → Настройки → Устройства → Подключить устройство</b> и наведите камеру.</p>
<img id="qr" src="{_qr_png(qr.url)}" alt="QR">
<p class="muted">Открыли эту страницу на том же телефоне? Отсканировать свой экран нельзя —
попробуйте кнопку ниже или откройте страницу на компьютере.</p>
<a id="tglink" href="{qr.url}"><button type="button">Открыть в Telegram на этом телефоне</button></a>
<p id="st" class="muted">Жду сканирования…</p>
<div id="pw" hidden><p>На аккаунте включён облачный пароль. Введите его (он никуда не сохраняется):</p>
<input id="p" type="password"><button id="pb">Войти</button></div>
<div id="ok" hidden><p><b>Готово!</b> Скопируйте строку ниже и вставьте в Render →
ваш сервис → <b>Environment</b> → переменная <code>TELEGRAM_SESSION</code> → <b>Save, rebuild, and deploy</b>. Сервер перезапустится сам.</p>
{guides.CSS}{guides.RENDER}
<textarea id="s" rows="6" readonly></textarea><button id="cp">Скопировать</button>
<p class="err">Эта строка = полный доступ к вашему Telegram. Не отправляйте её никому, даже ИИ.</p></div>
<script>
const id = "{pid}", k = "{key}";
async function poll() {{
  const r = await fetch(`/setup/status?id=${{id}}&k=${{k}}`); const j = await r.json();
  if (j.status === "pending") {{ if (j.qr) qr.src = j.qr; if (j.url) tglink.href = j.url; return setTimeout(poll, 2000); }}
  qr.hidden = true; tglink.hidden = true;
  if (j.status === "need_2fa") {{ st.textContent = ""; pw.hidden = false; return; }}
  if (j.status === "ok") {{ st.textContent = "Вошли как " + j.name; ok.hidden = false; s.value = j.session; return; }}
  st.textContent = "Не получилось (" + (j.error || j.status) + "). Обновите страницу и попробуйте снова.";
}}
pb.onclick = async () => {{
  const r = await fetch("/setup/2fa", {{method: "POST", headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{id, k, password: p.value}})}});
  const j = await r.json(); if (j.error) {{ st.textContent = j.error; return; }}
  pw.hidden = true; st.textContent = "Вошли как " + j.name; ok.hidden = false; s.value = j.session;
}};
cp.onclick = () => {{ navigator.clipboard.writeText(s.value); cp.textContent = "Скопировано"; }};
poll();
</script>""")


def _item(pid: str, key: str) -> dict | None:
    data = verify("setup", key)
    if not data or data["id"] != pid:
        return None
    return _pending.get(pid)


async def setup_status(request: Request):
    item = _item(request.query_params.get("id", ""), request.query_params.get("k", ""))
    if not item:
        return JSONResponse({"status": "expired"}, status_code=404)
    result = {"status": item["status"]}
    if item["status"] == "pending":
        result.update(qr=_qr_png(item["qr"].url), url=item["qr"].url)
    elif item["status"] == "ok":
        result.update(name=item["name"], session=item["session"])
        _pending.pop(request.query_params["id"], None)  # show the session only once
    elif item["status"] == "error":
        result["error"] = item.get("error")
    return JSONResponse(result)


async def setup_2fa(request: Request):
    body = await request.json()
    item = _item(str(body.get("id", "")), str(body.get("k", "")))
    if not item or item["status"] != "need_2fa":
        return JSONResponse({"error": "Сессия входа устарела, обновите страницу"}, status_code=404)
    if guard.locked():
        return JSONResponse({"error": "Слишком много попыток, подождите 15 минут"}, status_code=429)
    try:
        await item["client"].sign_in(password=str(body.get("password", "")))
    except PasswordHashInvalidError:
        guard.failures.append(time.time())
        return JSONResponse({"error": "Неверный облачный пароль"}, status_code=400)
    await _finish(item)
    _pending.pop(str(body["id"]), None)
    return JSONResponse({"name": item["name"], "session": item["session"]})
