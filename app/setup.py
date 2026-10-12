"""/setup: log the owner's Telegram account in, in the browser: QR (computer) or phone number + code (phone).

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
from telethon.errors import (FloodWaitError, PasswordHashInvalidError, PhoneCodeExpiredError,
                             PhoneCodeInvalidError, PhoneNumberInvalidError, SessionPasswordNeededError)

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
    return page("Подключение Telegram", """<p>Введите пароль сервера (ADMIN_PASSWORD), который вы задали в Render.</p>
<form method="post"><input type="password" name="password" placeholder="Пароль сервера" required autofocus>
<button>Дальше</button></form>""")


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
    _pending[pid]["task"] = asyncio.create_task(_wait(pid))
    key = sign("setup", {"id": pid}, LIFETIME)
    render_env = (f"https://dashboard.render.com/web/{config.RENDER_SERVICE_ID}/env"
                  if config.RENDER_SERVICE_ID else "https://dashboard.render.com")
    return page("Подключение Telegram", f"""
<div id="wait">
<div id="m-phone"><h3>Вход по номеру телефона</h3>
<p class="muted">Удобно, если вы открыли страницу на телефоне.</p>
<div id="ph1"><p class="err"><b>Номер полностью, с кодом страны:</b> +7 999 123-45-67.
Без «+7» (или с 8 в начале) код может не прийти.</p>
<input id="phone" type="tel" placeholder="+7 999 123-45-67" autocomplete="tel">
<button id="sendcode">Получить код</button></div>
<div id="ph2" hidden><p>Код отправлен на <b id="sentto"></b>. Он приходит <b>в приложение Telegram</b> (чат «Telegram»), не в SMS.
Откройте Telegram, скопируйте код и вернитесь сюда.</p>
<input id="code" inputmode="numeric" autocomplete="one-time-code" placeholder="Код из Telegram">
<button id="sendlogin">Войти</button></div></div>
<div id="m-qr"><h3>Вход по QR-коду</h3>
<p class="muted">Удобно, если страница открыта на компьютере: QR сканируете телефоном.</p>
<p>Telegram на телефоне → <b>Настройки → Устройства → Подключить устройство</b> → наведите камеру.</p>
<img id="qr" src="{_qr_png(qr.url)}" alt="QR"></div>
</div>
<p id="st" class="muted"></p>
<div id="pw" hidden><p>На аккаунте включён облачный пароль. Введите его (он никуда не сохраняется):</p>
<input id="p" type="password"><button id="pb">Войти</button></div>
<div id="ok" hidden>
<p class="err">Не делайте скриншот и не пересылайте строку: она = полный доступ к вашему Telegram.</p>
<h3>Шаг 1. Посмотрите, что нужно сделать в Render</h3>
<p>В Render: <b>Edit</b> → поле значения у <code>TELEGRAM_SESSION</code> (<b>5-я строка</b>) → вставить строку →
<b>Save, rebuild, and deploy</b>. Сервер перезапустится за 2–3 минуты.</p>
{guides.CSS}{guides.RENDER}
<h3>Шаг 2. Скопируйте строку</h3>
<button id="cp">Скопировать строку</button>
<button id="show" type="button" style="background:#e5e5ea;color:#1c1c1e">Показать строку</button>
<textarea id="s" rows="6" readonly hidden></textarea>
<h3>Шаг 3. Откройте Render и сделайте шаг 1</h3>
<button id="go" type="button" disabled>Сначала скопируйте строку (шаг 2)</button>
<p class="muted">Render откроется в новой вкладке. Эту страницу не закрывайте, пока не сохраните.</p></div>
<script>
const id = "{pid}", k = "{key}"; let session = "", finished = false;
// On a phone the phone-number method goes first, on a computer the QR.
if (matchMedia("(pointer: coarse)").matches) wait.prepend(document.getElementById("m-phone"));
else wait.prepend(document.getElementById("m-qr"));
function done(name, sess) {{
  finished = true; session = sess; wait.hidden = true; pw.hidden = true;
  st.textContent = "Вошли как " + name; ok.hidden = false; ok.scrollIntoView();
}}
function need2fa() {{ finished = true; wait.hidden = true; st.textContent = ""; pw.hidden = false; }}
async function post(path, data) {{
  const r = await fetch(path, {{method: "POST", headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{id, k, ...data}})}});
  return r.json();
}}
async function poll() {{
  if (finished) return;
  const r = await fetch(`/setup/status?id=${{id}}&k=${{k}}`); const j = await r.json();
  if (finished) return;
  if (j.status === "pending") {{ if (j.qr) qr.src = j.qr; return setTimeout(poll, 2000); }}
  if (j.status === "need_2fa") return need2fa();
  if (j.status === "ok") return done(j.name, j.session);
  wait.hidden = true;
  st.textContent = "Не получилось (" + (j.error || j.status) + "). Обновите страницу и попробуйте снова.";
}}
sendcode.onclick = async () => {{
  st.textContent = "Отправляю код…";
  const j = await post("/setup/phone", {{phone: phone.value}});
  if (j.error) {{ st.textContent = j.error; return; }}
  st.textContent = ""; sentto.textContent = j.phone; ph1.hidden = true; ph2.hidden = false; code.focus();
}};
sendlogin.onclick = async () => {{
  st.textContent = "Вхожу…";
  const j = await post("/setup/code", {{code: code.value}});
  if (j.error) {{ st.textContent = j.error; return; }}
  if (j.need_2fa) return need2fa();
  done(j.name, j.session);
}};
pb.onclick = async () => {{
  const j = await post("/setup/2fa", {{password: p.value}});
  if (j.error) {{ st.textContent = j.error; return; }}
  done(j.name, j.session);
}};
function unlock() {{ go.disabled = false; go.textContent = "Открыть Render → Environment"; }}
cp.onclick = async () => {{
  try {{ await navigator.clipboard.writeText(session); cp.textContent = "Скопировано ✓ — теперь шаг 3"; }}
  catch (e) {{ s.value = session; s.hidden = false; s.select(); cp.textContent = "Выделено — нажмите Копировать"; }}
  unlock();
}};
s.addEventListener("copy", unlock);
go.onclick = () => window.open("{render_env}", "_blank", "noopener");
show.onclick = () => {{ s.value = session; s.hidden = !s.hidden; show.textContent = s.hidden ? "Показать строку" : "Скрыть строку"; }};
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
        result["qr"] = _qr_png(item["qr"].url)
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
    item["task"].cancel()
    await _finish(item)
    _pending.pop(str(body["id"]), None)
    return JSONResponse({"name": item["name"], "session": item["session"]})


def normalize_phone(raw: str) -> str:
    """'+7 (999) 123-45-67' / '89991234567' / '79991234567' -> '+79991234567'; '' if too short."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 11 and digits.startswith("8") and not raw.strip().startswith("+"):
        digits = "7" + digits[1:]  # Russian habit: 8 instead of +7
    if len(digits) == 10 and digits.startswith("9") and not raw.strip().startswith("+"):
        digits = "7" + digits  # 999... without country code
    return "+" + digits if 11 <= len(digits) <= 15 else ""


async def setup_phone(request: Request):
    """Phone-number login, step 1: Telegram sends a code into the Telegram app."""
    body = await request.json()
    item = _item(str(body.get("id", "")), str(body.get("k", "")))
    if not item or item["status"] != "pending":
        return JSONResponse({"error": "Сессия входа устарела, обновите страницу"}, status_code=404)
    phone = normalize_phone(str(body.get("phone", "")))
    if not phone:
        return JSONResponse({"error": "Введите номер полностью, с кодом страны: +7 999 123-45-67"}, status_code=400)
    try:
        sent = await item["client"].send_code_request(phone)
    except PhoneNumberInvalidError:
        return JSONResponse({"error": "Telegram не знает такой номер"}, status_code=400)
    except FloodWaitError as exc:
        return JSONResponse({"error": f"Telegram просит подождать {exc.seconds // 60 + 1} мин."}, status_code=429)
    item.update(phone=phone, phone_code_hash=sent.phone_code_hash)
    return JSONResponse({"sent": True, "phone": phone})


async def setup_code(request: Request):
    """Phone-number login, step 2: the code from the Telegram app."""
    body = await request.json()
    pid = str(body.get("id", ""))
    item = _item(pid, str(body.get("k", "")))
    if not item or "phone_code_hash" not in item:
        return JSONResponse({"error": "Сначала запросите код"}, status_code=400)
    if guard.locked():
        return JSONResponse({"error": "Слишком много попыток, подождите 15 минут"}, status_code=429)
    code = "".join(ch for ch in str(body.get("code", "")) if ch.isdigit())
    try:
        await item["client"].sign_in(item["phone"], code, phone_code_hash=item["phone_code_hash"])
    except SessionPasswordNeededError:
        item["status"] = "need_2fa"
        return JSONResponse({"need_2fa": True})
    except PhoneCodeInvalidError:
        guard.failures.append(time.time())
        return JSONResponse({"error": "Неверный код, проверьте и введите ещё раз"}, status_code=400)
    except PhoneCodeExpiredError:
        return JSONResponse({"error": "Код устарел — обновите страницу и запросите новый"}, status_code=400)
    item["task"].cancel()
    await _finish(item)
    _pending.pop(pid, None)
    return JSONResponse({"name": item["name"], "session": item["session"]})
