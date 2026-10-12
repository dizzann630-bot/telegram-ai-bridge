"""/setup login flows with a fake Telegram client (no network)."""
import asyncio
import json
import os
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "k" * 64)
os.environ["ADMIN_PASSWORD"] = "correct-horse-1"
os.environ.setdefault("TELEGRAM_API_ID", "1")
os.environ.setdefault("TELEGRAM_API_HASH", "x")

from telethon.errors import PhoneCodeInvalidError, SessionPasswordNeededError  # noqa: E402

from app import config, setup  # noqa: E402

config.ADMIN_PASSWORD = "correct-horse-1"
config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH = 1, "x"


class FakeQR:
    url = "tg://login?token=FAKE"

    async def wait(self, timeout=None):
        await asyncio.sleep(3600)


class FakeClient:
    def __init__(self, two_fa=False):
        self.two_fa, self.signed = two_fa, False
        self.session = SimpleNamespace(save=lambda: "SESSION-STRING")

    async def connect(self): pass
    async def disconnect(self): pass
    async def qr_login(self): return FakeQR()
    async def send_code_request(self, phone): return SimpleNamespace(phone_code_hash="HASH")

    async def sign_in(self, phone=None, code=None, password=None, phone_code_hash=None):
        if password is not None:
            if password != "cloud-pass":
                from telethon.errors import PasswordHashInvalidError
                raise PasswordHashInvalidError(request=None)
            return
        if code != "12345" or phone_code_hash != "HASH":
            raise PhoneCodeInvalidError(request=None)
        if self.two_fa:
            raise SessionPasswordNeededError(request=None)

    async def get_me(self): return SimpleNamespace(first_name="Yooka", last_name=None)


class Req:
    def __init__(self, form=None, body=None):
        self._form, self._body = form, body

    async def form(self): return self._form
    async def json(self): return self._body


def start(two_fa=False):
    setup.guard.failures.clear()
    setup.new_client = lambda *a: FakeClient(two_fa)

    async def go():
        page = (await setup.setup_submit(Req(form={"password": "correct-horse-1"}))).body.decode()
        pid = page.split('const id = "')[1].split('"')[0]
        key = page.split('k = "')[1].split('"')[0]
        return page, pid, key
    return go


def call(fn, body):
    return json.loads(asyncio.get_event_loop().run_until_complete(fn(Req(body=body))).body)


def test_phone_login_and_2fa():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    page, pid, key = loop.run_until_complete(start()())
    assert "Вход по номеру телефона" in page and "Вход по QR-коду" in page and "tglink" not in page
    assert call(setup.setup_phone, {"id": pid, "k": key, "phone": "123"})["error"]
    assert call(setup.setup_phone, {"id": pid, "k": key, "phone": "+7 999 123-45-67"}) == {"sent": True, "phone": "+79991234567"}
    for raw in ("89991234567", "8 (999) 123-45-67", "9991234567", "79991234567"):
        assert setup.normalize_phone(raw) == "+79991234567", raw
    assert setup.normalize_phone("+380 67 123 4567") == "+380671234567"
    assert "Неверный код" in call(setup.setup_code, {"id": pid, "k": key, "code": "00000"})["error"]
    ok = call(setup.setup_code, {"id": pid, "k": key, "code": "12 345"})
    assert ok == {"name": "Yooka", "session": "SESSION-STRING"}
    assert pid not in setup._pending  # shown once

    page, pid, key = loop.run_until_complete(start(two_fa=True)())
    call(setup.setup_phone, {"id": pid, "k": key, "phone": "+79991234567"})
    assert call(setup.setup_code, {"id": pid, "k": key, "code": "12345"}) == {"need_2fa": True}
    assert "Неверный облачный пароль" in call(setup.setup_2fa, {"id": pid, "k": key, "password": "x"})["error"]
    assert call(setup.setup_2fa, {"id": pid, "k": key, "password": "cloud-pass"})["session"] == "SESSION-STRING"
    assert call(setup.setup_code, {"id": "bad", "k": "bad", "code": "1"})["error"]
    loop.close()
