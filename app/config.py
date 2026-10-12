"""Settings from environment variables (Render secrets)."""
from __future__ import annotations

import os
from urllib.parse import urlparse


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


SECRET_KEY = _env("SECRET_KEY").encode()
ADMIN_PASSWORD = _env("ADMIN_PASSWORD")
TELEGRAM_API_ID = int(_env("TELEGRAM_API_ID", "0") or 0)
TELEGRAM_API_HASH = _env("TELEGRAM_API_HASH")
TELEGRAM_SESSION = _env("TELEGRAM_SESSION")
TIMEZONE = _env("TIMEZONE", "Europe/Moscow")

# Render sets RENDER_EXTERNAL_URL automatically; PUBLIC_URL overrides it.
PUBLIC_URL = (_env("PUBLIC_URL") or _env("RENDER_EXTERNAL_URL") or "http://localhost:8000").rstrip("/")
PUBLIC_HOST = urlparse(PUBLIC_URL).netloc

SCOPE = "telegram"
MIN_PASSWORD_LENGTH = 10


def secret() -> bytes:
    if len(SECRET_KEY) < 32:
        raise RuntimeError("SECRET_KEY must be at least 32 characters")
    return SECRET_KEY


def password_ready() -> bool:
    return len(ADMIN_PASSWORD) >= MIN_PASSWORD_LENGTH
