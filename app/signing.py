"""Stateless signed tokens: HMAC-SHA256 over compact JSON. No database needed."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from . import config


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(kind: str, body: str) -> str:
    return _b64(hmac.new(config.secret(), f"{kind}.{body}".encode(), hashlib.sha256).digest())


def sign(kind: str, data: dict, ttl_seconds: int) -> str:
    payload = {"k": kind, "exp": int(time.time()) + ttl_seconds, **data}
    body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    return f"{body}.{_mac(kind, body)}"


def verify(kind: str, token: str) -> dict | None:
    """Return the payload if the token is ours, of this kind and not expired."""
    try:
        body, mac = token.split(".", 1)
        if not hmac.compare_digest(mac, _mac(kind, body)):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if payload.get("k") != kind or payload.get("exp", 0) < time.time():
        return None
    return payload


def derive(label: str, value: str) -> str:
    """Deterministic secret derived from SECRET_KEY (e.g. a client_secret)."""
    return hmac.new(config.secret(), f"{label}:{value}".encode(), hashlib.sha256).hexdigest()
