"""Telegram MCP server for ChatGPT and Claude. Run: uvicorn app.server:app"""
from __future__ import annotations

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse

from . import config, oauth, setup, tg, uploads

INSTRUCTIONS = """Доступ к Telegram владельца сервера.
- Найти чат: list_chats (id нужен всем остальным инструментам).
- Читать: read_chat (последние сообщения), export_chat (вся переписка частями, продолжай с next_after_id),
  search_messages (по одному чату или везде, dialog_id=0).
- Каналы: channel_info, similar_channels (похожие каналы).
- Файлы: в ChatGPT прикреплённые пользователем файлы передай в attach_chatgpt_files; иначе get_upload_link
  (дай ссылку пользователю или загрузи сам: curl -F file=@путь <ссылка>), по ссылке из интернета — upload_from_url.
  Получишь upload_ids. После загрузки по ссылке пользователем — list_uploads.
- Отправить сообщение: preview_message → покажи пользователю получателя, текст и файлы → только после его явного
  согласия send_message с тем же preview_token. Никогда не отправляй без согласия.
- Отложенный пост в свой канал/группу/Избранное: schedule_post (время ISO, по Москве если без пояса),
  проверить очередь — list_scheduled. Отмена — в самом Telegram."""

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)

mcp = FastMCP(
    "Telegram",
    instructions=INSTRUCTIONS,
    auth_server_provider=oauth.provider,
    auth=AuthSettings(
        issuer_url=config.PUBLIC_URL,
        resource_server_url=f"{config.PUBLIC_URL}/mcp",
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[config.SCOPE], default_scopes=[config.SCOPE]),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[config.SCOPE],
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(
        allowed_hosts=[config.PUBLIC_HOST, "localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"]),
)


class ChatGPTFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    download_url: str
    file_id: str
    mime_type: str = ""
    file_name: str = ""


# ---------------------------------------------------------------- reading
@mcp.tool(annotations=READ)
async def whoami() -> dict:
    """Чей Telegram подключён к серверу."""
    return await tg.whoami()


@mcp.tool(annotations=READ)
async def list_chats(query: str = "", limit: int = 50) -> list[dict]:
    """Чаты, группы и каналы (свежие сверху). query — фильтр по названию. Возвращает id для других инструментов."""
    return await tg.list_chats(query, limit)


@mcp.tool(annotations=READ)
async def read_chat(dialog_id: int, limit: int = 50, before_id: int = 0) -> dict:
    """Последние сообщения чата. Старее: before_id=next_before_id."""
    return await tg.read_chat(dialog_id, limit, before_id)


@mcp.tool(annotations=READ)
async def search_messages(query: str, dialog_id: int = 0, limit: int = 30) -> dict:
    """Поиск по тексту в одном чате (dialog_id) или во всех (dialog_id=0)."""
    return await tg.search(query, dialog_id, limit)


@mcp.tool(annotations=READ)
async def export_chat(dialog_id: int, after_id: int = 0, max_chars: int = 40000) -> dict:
    """Вся переписка от старых к новым, частями. Если complete=false — вызови снова с after_id=next_after_id."""
    return await tg.export_chat(dialog_id, after_id, max_chars)


@mcp.tool(annotations=READ)
async def channel_info(channel: str) -> dict:
    """Публичный канал: название, подписчики, описание. channel = @username или ссылка t.me."""
    return await tg.channel_info(channel)


@mcp.tool(annotations=READ)
async def similar_channels(channel: str) -> list[dict]:
    """Похожие каналы (рекомендации Telegram) для публичного канала."""
    return await tg.similar_channels(channel)


@mcp.tool(annotations=READ)
async def list_scheduled(dialog_id: int) -> dict:
    """Отложенные сообщения в чате/канале."""
    return await tg.list_scheduled(dialog_id)


# ---------------------------------------------------------------- files
@mcp.tool(annotations=READ)
async def get_upload_link() -> dict:
    """Одноразовая ссылка загрузки файлов (1 час). Дай её пользователю или загрузи сам через curl."""
    link = uploads.new_link()
    return {"link": link, "curl": f'curl -F "file=@ФАЙЛ.jpg" "{link}"',
            "next": "После загрузки пользователем вызови list_uploads"}


@mcp.tool(annotations=READ)
async def list_uploads() -> list[dict]:
    """Недавно загруженные файлы (живут 1 час): id, имя, размер, тип."""
    return uploads.recent()


@mcp.tool(annotations=WRITE, meta={"openai/fileParams": ["files"]})
async def attach_chatgpt_files(files: list[ChatGPTFile]) -> list[dict]:
    """ChatGPT: передай сюда файлы, которые пользователь прикрепил к сообщению. Вернёт upload_ids."""
    if len(files) > uploads.MAX_FILES:
        raise ValueError(f"Не больше {uploads.MAX_FILES} файлов")
    return [await uploads.download_chatgpt(f.download_url, f.file_name) for f in files]


@mcp.tool(annotations=WRITE)
async def upload_from_url(url: str, file_name: str = "") -> dict:
    """Скачать файл по публичной https-ссылке (до 20 МБ). Вернёт upload id."""
    return await uploads.download(url, file_name)


# ---------------------------------------------------------------- sending
@mcp.tool(annotations=READ)
async def preview_message(dialog_id: int, text: str = "", upload_ids: list[str] = [],
                          mode: str = "media") -> dict:
    """Шаг 1 отправки: проверяет получателя и права, ничего не отправляет. mode: media (фото/видео альбомом)
    или documents (файлы без сжатия). Покажи результат пользователю и дождись согласия."""
    return await tg.preview_send(dialog_id, text, upload_ids, mode)


@mcp.tool(annotations=WRITE)
async def send_message(dialog_id: int, preview_token: str, text: str = "", upload_ids: list[str] = [],
                       mode: str = "media", markdown: bool = False) -> dict:
    """Шаг 2: отправить ровно то, что было в preview_message, только после согласия пользователя."""
    return await tg.send(dialog_id, text, upload_ids, mode, preview_token, markdown)


@mcp.tool(annotations=WRITE)
async def schedule_post(dialog_id: int, scheduled_at: str, text: str = "", upload_ids: list[str] = [],
                        mode: str = "media", markdown: bool = True) -> dict:
    """Отложенный пост в свой канал/группу (где вы админ) или Избранное. scheduled_at: 2026-10-15T10:00
    (по Москве, если без пояса). Фото: upload_ids, подпись идёт к альбому."""
    return await tg.schedule_post(dialog_id, text, scheduled_at, upload_ids, mode, markdown)


# ---------------------------------------------------------------- web pages
@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    import os
    return JSONResponse({"ok": True, "version": os.getenv("RENDER_GIT_COMMIT", "local")[:7],
                         "telegram_configured": bool(config.TELEGRAM_SESSION),
                         "telegram_keys_set": bool(config.TELEGRAM_API_ID and config.TELEGRAM_API_HASH),
                         "password_set": config.password_ready(),
                         "password_too_short": 0 < len(config.ADMIN_PASSWORD) < config.MIN_PASSWORD_LENGTH})


mcp.custom_route("/login", methods=["GET"])(oauth.login_page)
mcp.custom_route("/login", methods=["POST"])(oauth.login_submit)
mcp.custom_route("/setup", methods=["GET"])(setup.setup_page)
mcp.custom_route("/setup", methods=["POST"])(setup.setup_submit)
mcp.custom_route("/setup/status", methods=["GET"])(setup.setup_status)
mcp.custom_route("/setup/2fa", methods=["POST"])(setup.setup_2fa)
mcp.custom_route("/upload", methods=["GET"])(uploads.upload_page)
mcp.custom_route("/upload", methods=["POST"])(uploads.upload_submit)

app = mcp.streamable_http_app()
