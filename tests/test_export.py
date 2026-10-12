"""Export logic with a fake Telegram chat (no network)."""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "k" * 64)

from app import exports  # noqa: E402
from app.signing import verify  # noqa: E402


def msg(i, when, text, out=False, sender=7, name="Настя", file=None):
    return SimpleNamespace(id=i, date=when, message=text, out=out, sender_id=sender,
                           sender=SimpleNamespace(first_name=name, last_name=None, id=sender) if not out else None,
                           reply_to=None, file=file, photo=None, video_note=None, gif=None, video=None,
                           voice=None, audio=None, sticker=None, document=file)


class FakeClient:
    def __init__(self, messages):
        self.messages = messages

    async def iter_messages(self, entity, reverse, offset_date, limit, wait_time):
        for m in self.messages:
            if offset_date is None or m.date > offset_date:
                yield m


def run(messages, **kw):
    fake = FakeClient(messages)

    @asynccontextmanager
    async def client():
        yield fake

    async def dialog(c, dialog_id):
        return SimpleNamespace(name="Настя", input_entity=None)

    exports.client, exports._dialog = client, dialog
    return asyncio.run(exports.export_chat(1, **kw))


def test_format_and_days():
    t0 = datetime(2026, 9, 12, 11, 3, tzinfo=timezone.utc)  # 14:03 MSK
    doc = SimpleNamespace(name="a.xlsx")
    msgs = [msg(1, t0, "привет\nкак дела"), msg(2, t0 + timedelta(minutes=1), "норм", out=True),
            msg(3, t0 + timedelta(days=1), "", file=doc)]
    r = run(msgs)
    text = exports.get_part(r["export_id"], 1)["text"]
    assert text.splitlines() == ["=== 12.09.2026 ===", "14:03 Настя: привет ⏎ как дела", "14:04 Я: норм",
                                 "=== 13.09.2026 ===", "14:03 Настя: [файл: a.xlsx]"]
    assert r["complete"] and r["messages"] == 3
    token = r["parts"][0]["download_url"].split("t=", 1)[1]
    assert verify("export", token)["id"] == r["export_id"]


def test_parts_and_date_filter():
    t0 = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    msgs = [msg(i, t0 + timedelta(hours=i), "х" * 300) for i in range(200)]
    r = run(msgs, chunk_tokens=2000)
    assert len(r["parts"]) > 1
    for p in range(1, len(r["parts"]) + 1):
        assert exports.get_part(r["export_id"], p)["text"].startswith("=== ")  # each part has a day header
    r2 = run(msgs, date_from="2026-09-03", date_to="2026-09-03")
    days = {line for line in exports.get_part(r2["export_id"], 1)["text"].splitlines() if line.startswith("===")}
    assert days == {"=== 03.09.2026 ==="}
