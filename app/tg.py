"""Telegram operations on the owner's account (Telethon, StringSession from Render secret)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telethon import TelegramClient, types, utils
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetChannelRecommendationsRequest, GetFullChannelRequest

from . import config, uploads
from .signing import sign, verify


class TelegramError(RuntimeError):
    pass


def new_client(session: str = "") -> TelegramClient:
    if not config.TELEGRAM_API_ID or not config.TELEGRAM_API_HASH:
        raise TelegramError("На сервере не заданы TELEGRAM_API_ID и TELEGRAM_API_HASH")
    return TelegramClient(StringSession(session), config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH,
                          timeout=10, connection_retries=2)


@asynccontextmanager
async def client():
    if not config.TELEGRAM_SESSION:
        raise TelegramError(f"Telegram ещё не подключён. Откройте {config.PUBLIC_URL}/setup")
    c = new_client(config.TELEGRAM_SESSION)
    try:
        await asyncio.wait_for(c.connect(), 30)
    except (asyncio.TimeoutError, OSError) as exc:
        raise TelegramError("Нет связи с серверами Telegram, попробуйте позже") from exc
    try:
        if not await c.is_user_authorized():
            raise TelegramError(f"Сессия Telegram недействительна. Подключите заново: {config.PUBLIC_URL}/setup")
        yield c
    finally:
        await c.disconnect()


# ---------------------------------------------------------------- formatting
def msk(moment: datetime) -> str:
    return moment.astimezone(ZoneInfo(config.TIMEZONE)).strftime("%d.%m.%Y %H:%M")


def kind_of(m) -> str:
    for attr, label in (("photo", "photo"), ("video_note", "round_video"), ("gif", "gif"),
                        ("video", "video"), ("voice", "voice"), ("audio", "audio"),
                        ("sticker", "sticker"), ("document", "file")):
        if getattr(m, attr, None):
            return label
    return "text"


def line(m, sender_names: dict | None = None) -> str:
    who = "я" if m.out else (sender_names or {}).get(m.sender_id, str(m.sender_id))
    kind = kind_of(m)
    text = (m.message or "").replace("\n", " ⏎ ")
    media = f" [{kind}]" if kind != "text" else ""
    return f"#{m.id} {msk(m.date)} {who}:{media} {text}".rstrip()


def _name(entity) -> str:
    if isinstance(entity, types.User):
        return " ".join(x for x in (entity.first_name, entity.last_name) if x) or str(entity.id)
    return getattr(entity, "title", str(getattr(entity, "id", "")))


async def _dialog(c, dialog_id: int):
    async for d in c.iter_dialogs(limit=None):
        if d.id == dialog_id:
            return d
    raise TelegramError("Диалог не найден. Возьмите id из list_chats")


async def _names(c, messages) -> dict:
    names = {}
    for m in messages:
        if m.sender_id and m.sender_id not in names and not m.out:
            sender = m.sender or await m.get_sender()
            names[m.sender_id] = _name(sender) if sender else str(m.sender_id)
    return names


# ---------------------------------------------------------------- reading
async def whoami() -> dict:
    async with client() as c:
        me = await c.get_me()
        return {"id": me.id, "name": _name(me), "username": me.username}


async def list_chats(query: str = "", limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 200))
    found = []
    async with client() as c:
        async for d in c.iter_dialogs(limit=1000):
            if query.casefold() not in (d.name or "").casefold():
                continue
            kind = "user" if d.is_user else "channel" if d.is_channel and getattr(d.entity, "broadcast", False) else "group"
            found.append({"id": d.id, "name": d.name, "username": getattr(d.entity, "username", None),
                          "kind": kind, "unread": d.unread_count})
            if len(found) >= limit:
                break
    return found


async def read_chat(dialog_id: int, limit: int = 50, before_id: int = 0) -> dict:
    limit = max(1, min(limit, 200))
    async with client() as c:
        d = await _dialog(c, dialog_id)
        msgs = [m async for m in c.iter_messages(d.input_entity, limit=limit, offset_id=before_id)]
        names = await _names(c, msgs)
    return {"chat": d.name, "messages": "\n".join(line(m, names) for m in reversed(msgs)),
            "next_before_id": msgs[-1].id if msgs else None}


async def search(query: str, dialog_id: int = 0, limit: int = 30) -> dict:
    limit = max(1, min(limit, 100))
    async with client() as c:
        entity = (await _dialog(c, dialog_id)).input_entity if dialog_id else None
        msgs = [m async for m in c.iter_messages(entity, search=query, limit=limit)]
        names = await _names(c, msgs)
        rows = []
        for m in msgs:
            chat = "" if dialog_id else f"[чат {utils.get_peer_id(m.peer_id)}] "
            rows.append(chat + line(m, names))
    return {"query": query, "results": "\n".join(rows) or "Ничего не найдено"}


async def export_chat(dialog_id: int, after_id: int = 0, max_chars: int = 40000) -> dict:
    """Whole history oldest-first in parts; continue with after_id=next_after_id."""
    max_chars = max(2000, min(max_chars, 80000))
    out, size, last_id, complete = [], 0, after_id, True
    async with client() as c:
        d = await _dialog(c, dialog_id)
        names: dict = {}
        async for m in c.iter_messages(d.input_entity, reverse=True, min_id=after_id):
            if m.sender_id and m.sender_id not in names and not m.out:
                s = m.sender or await m.get_sender()
                names[m.sender_id] = _name(s) if s else str(m.sender_id)
            row = line(m, names)
            if size + len(row) > max_chars:
                complete = False
                break
            out.append(row)
            size += len(row) + 1
            last_id = m.id
    return {"chat": d.name, "text": "\n".join(out), "next_after_id": last_id, "complete": complete}


async def channel_info(channel: str) -> dict:
    async with client() as c:
        e = await c.get_entity(channel)
        full = await c(GetFullChannelRequest(e))
        return {"id": utils.get_peer_id(e), "title": e.title, "username": e.username,
                "subscribers": full.full_chat.participants_count, "about": full.full_chat.about}


async def similar_channels(channel: str) -> list[dict]:
    async with client() as c:
        e = await c.get_entity(channel)
        res = await c(GetChannelRecommendationsRequest(channel=e))
        return [{"title": ch.title, "username": ch.username,
                 "subscribers": getattr(ch, "participants_count", None)}
                for ch in res.chats if getattr(ch, "username", None)]


# ---------------------------------------------------------------- sending
async def _target(c, dialog_id: int, has_files: bool):
    d = await _dialog(c, dialog_id)
    e = d.entity
    if isinstance(e, types.User):
        if e.deleted:
            raise TelegramError("Получатель удалён")
        kind = "bot" if e.bot else "self" if e.is_self else "user"
    else:
        if getattr(e, "left", False) or getattr(e, "deactivated", False):
            raise TelegramError("Вы не состоите в этом чате")
        kind = "channel" if getattr(e, "broadcast", False) else "group"
        creator, admin = bool(getattr(e, "creator", False)), getattr(e, "admin_rights", None)
        if kind == "channel" and not creator and not (admin and admin.post_messages):
            raise TelegramError("Нет прав публиковать в этом канале")
        banned = getattr(e, "default_banned_rights", None)
        if kind == "group" and not creator and not admin and banned:
            if banned.send_messages or (has_files and banned.send_media):
                raise TelegramError("В этой группе вам запрещено отправлять такое сообщение")
    own = kind == "self" or (kind in ("channel", "group") and
                             (getattr(e, "creator", False) or getattr(e, "admin_rights", None)))
    return d, {"dialog_id": dialog_id, "name": d.name, "kind": kind,
               "username": getattr(e, "username", None), "own": bool(own)}


def _files(upload_ids: list[str], mode: str) -> list[dict]:
    if mode not in ("media", "documents"):
        raise TelegramError("mode: media (фото/видео альбомом) или documents (файлы без сжатия)")
    files = uploads.get(upload_ids)
    if mode == "media":
        bad = [f["name"] for f in files if f["kind"] not in uploads.PHOTO_KINDS | {"mp4", "gif"}]
        if bad:
            raise TelegramError(f"Это не фото/видео: {', '.join(bad)}. Используйте mode=documents")
    return files


def _digest(dialog_id, text, files, mode, when="") -> str:
    data = {"d": dialog_id, "t": text, "f": [f["sha256"] for f in files], "m": mode, "w": when}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _check_text(text: str, files: list) -> None:
    if not text.strip() and not files:
        raise TelegramError("Нужен текст или файлы")
    if len(text) > 4096:
        raise TelegramError("Текст длиннее 4096 символов")


async def _deliver(c, entity, text, files, mode, parse_mode, schedule=None):
    if not files:
        msg = await c.send_message(entity, text, parse_mode=parse_mode, schedule=schedule,
                                   link_preview=True)
        return [msg.id]
    paths = [f["path"] for f in files]
    if mode == "media":
        caption = [text] + [""] * (len(paths) - 1) if len(paths) > 1 else text
        sent = await c.send_file(entity, paths if len(paths) > 1 else paths[0], caption=caption,
                                 parse_mode=parse_mode, schedule=schedule, force_document=False)
        sent = sent if isinstance(sent, list) else [sent]
        return [m.id for m in sent]
    ids = []
    for i, path in enumerate(paths):
        m = await c.send_file(entity, path, caption=text if i == 0 else "", parse_mode=parse_mode,
                              schedule=schedule, force_document=True)
        ids.append(m.id)
    return ids


_used_previews: dict[str, float] = {}


async def preview_send(dialog_id: int, text: str, upload_ids: list[str], mode: str) -> dict:
    files = _files(upload_ids, mode) if upload_ids else []
    _check_text(text, files)
    async with client() as c:
        _, target = await _target(c, dialog_id, bool(files))
    token = sign("send", {"dg": _digest(dialog_id, text, files, mode), "tg": target}, 600)
    return {"recipient": target, "text": text, "files": [uploads.public(f) for f in files],
            "mode": mode, "preview_token": token, "valid_minutes": 10,
            "next": "Покажите пользователю получателя и текст. После его «да» вызовите send_message "
                    "с теми же параметрами и этим preview_token."}


async def send(dialog_id: int, text: str, upload_ids: list[str], mode: str,
               preview_token: str, markdown: bool = False) -> dict:
    files = _files(upload_ids, mode) if upload_ids else []
    _check_text(text, files)
    approved = verify("send", preview_token)
    if not approved or approved["dg"] != _digest(dialog_id, text, files, mode):
        raise TelegramError("Предпросмотр устарел или параметры изменились — сделайте preview_message заново")
    now = time.time()
    for k in [k for k, exp in _used_previews.items() if exp < now]:
        _used_previews.pop(k)
    if preview_token in _used_previews:
        raise TelegramError("Это сообщение уже отправлено по этому предпросмотру")
    async with client() as c:
        d, target = await _target(c, dialog_id, bool(files))
        if target != approved["tg"]:
            raise TelegramError("Получатель изменился — сделайте предпросмотр заново")
        # Duplicate guard without a database: same text sent here in the last 10 minutes?
        if text.strip():
            async for m in c.iter_messages(d.input_entity, limit=15):
                if m.out and (m.message or "") == text and (now - m.date.timestamp()) < 600:
                    raise TelegramError(f"Такое сообщение уже ушло в этот чат (#{m.id}) меньше 10 минут назад")
        _used_previews[preview_token] = approved["exp"]
        ids = await _deliver(c, d.input_entity, text, files, mode, "md" if markdown else None)
    return {"sent": True, "recipient": target, "message_ids": ids}


def parse_when(value: str) -> datetime:
    try:
        when = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TelegramError("Время в формате 2026-10-15T10:00 (по Москве, если без пояса)") from exc
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo(config.TIMEZONE))
    now = datetime.now(when.tzinfo)
    if not now + timedelta(minutes=1) <= when <= now + timedelta(days=365):
        raise TelegramError("Время должно быть в будущем, но не дальше года")
    return when


async def schedule_post(dialog_id: int, text: str, scheduled_at: str, upload_ids: list[str],
                        mode: str, markdown: bool = True) -> dict:
    files = _files(upload_ids, mode) if upload_ids else []
    _check_text(text, files)
    when = parse_when(scheduled_at)
    async with client() as c:
        d, target = await _target(c, dialog_id, bool(files))
        if not target["own"]:
            raise TelegramError("Отложенные посты — только в свои каналы/группы (где вы админ) и в «Избранное»")
        ids = await _deliver(c, d.input_entity, text, files, mode, "md" if markdown else None, when)
    return {"scheduled": True, "chat": target["name"], "when": msk(when), "message_ids": ids,
            "note": "Пост в очереди Telegram. Изменить или отменить можно в Telegram: отложенные сообщения."}


async def list_scheduled(dialog_id: int) -> dict:
    async with client() as c:
        d = await _dialog(c, dialog_id)
        msgs = [m async for m in c.iter_messages(d.input_entity, scheduled=True)]
    return {"chat": d.name, "scheduled": [
        {"id": m.id, "when": msk(m.date), "kind": kind_of(m), "text": (m.message or "")[:300]}
        for m in sorted(msgs, key=lambda m: m.date)]}
