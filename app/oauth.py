"""Built-in OAuth for one owner: the password from ADMIN_PASSWORD.

Everything (clients, codes, tokens) is a signed token, so Render restarts
do not log anyone out and no database is needed. To revoke all access,
change SECRET_KEY in Render.
"""
from __future__ import annotations

import asyncio
import hmac
import html
import time

from mcp.server.auth.provider import (AccessToken, AuthorizationCode, AuthorizationParams,
                                      OAuthAuthorizationServerProvider, RefreshToken,
                                      construct_redirect_uri)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from . import config
from .signing import derive, sign, verify

ACCESS_TTL = 3600
REFRESH_TTL = 90 * 24 * 3600
CODE_TTL = 300
CLIENT_TTL = 10 * 365 * 24 * 3600


# ---------------------------------------------------------------- password guard
class PasswordGuard:
    """Global limiter: one owner per server, so lock after repeated failures."""

    def __init__(self, max_failures: int = 5, window: int = 900):
        self.max_failures, self.window = max_failures, window
        self.failures: list[float] = []

    def locked(self) -> bool:
        now = time.time()
        self.failures = [t for t in self.failures if now - t < self.window]
        return len(self.failures) >= self.max_failures

    async def check(self, password: str) -> str | None:
        """Return None if correct, else a human-readable error."""
        if not config.password_ready():
            return "На сервере не задан ADMIN_PASSWORD (минимум 10 символов)."
        if self.locked():
            return "Слишком много неверных попыток. Подождите 15 минут."
        if hmac.compare_digest(password.encode(), config.ADMIN_PASSWORD.encode()):
            return None
        self.failures.append(time.time())
        await asyncio.sleep(1)
        return "Неверный пароль."


guard = PasswordGuard()


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>body{{font:16px system-ui,sans-serif;max-width:440px;margin:40px auto;padding:0 16px;color:#1c1c1e}}
input,button,textarea{{font:inherit;width:100%;box-sizing:border-box;padding:12px;margin:8px 0;border-radius:10px;border:1px solid #c7c7cc}}
button{{background:#2a7de1;color:#fff;border:0;cursor:pointer}}.err{{color:#c62828}}.muted{{color:#6e6e73;font-size:14px}}
code,textarea{{font-family:ui-monospace,monospace;font-size:13px}}img{{width:100%;image-rendering:pixelated}}</style>
</head><body><h2>{html.escape(title)}</h2>{body}</body></html>""")


# ---------------------------------------------------------------- provider
class OwnerOAuthProvider(OAuthAuthorizationServerProvider):
    def __init__(self):
        self.used_codes: dict[str, float] = {}

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        data = {"r": [str(u) for u in client_info.redirect_uris or []],
                "m": client_info.token_endpoint_auth_method or "client_secret_post",
                "g": list(client_info.grant_types or ["authorization_code", "refresh_token"]),
                "n": (client_info.client_name or "")[:60]}
        # The SDK returns this same object to the client, so we set our stateless ID here.
        client_info.client_id = "c." + sign("client", data, CLIENT_TTL)
        client_info.client_secret = (None if data["m"] == "none"
                                     else derive("client-secret", client_info.client_id))
        client_info.client_secret_expires_at = None

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if not client_id.startswith("c."):
            return None
        data = verify("client", client_id[2:])
        if not data:
            return None
        return OAuthClientInformationFull(
            client_id=client_id,
            client_secret=None if data["m"] == "none" else derive("client-secret", client_id),
            redirect_uris=data["r"], token_endpoint_auth_method=data["m"],
            grant_types=data["g"], response_types=["code"], client_name=data["n"] or None,
            scope=config.SCOPE)

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        request = sign("authreq", {
            "cid": client.client_id, "ru": str(params.redirect_uri),
            "rue": params.redirect_uri_provided_explicitly, "cc": params.code_challenge,
            "st": params.state, "sc": params.scopes or [config.SCOPE], "res": params.resource,
            "name": client.client_name or ""}, 600)
        return f"{config.PUBLIC_URL}/login?req={request}"

    async def load_authorization_code(self, client, authorization_code: str):
        data = verify("code", authorization_code)
        if not data or data["cid"] != client.client_id or authorization_code in self.used_codes:
            return None
        return AuthorizationCode(code=authorization_code, scopes=data["sc"], expires_at=data["exp"],
                                 client_id=data["cid"], code_challenge=data["cc"],
                                 redirect_uri=data["ru"], redirect_uri_provided_explicitly=data["rue"],
                                 resource=data.get("res"))

    def _tokens(self, client_id: str, scopes: list[str], resource: str | None) -> OAuthToken:
        claims = {"cid": client_id, "sc": scopes, "res": resource}
        return OAuthToken(access_token="a." + sign("access", claims, ACCESS_TTL),
                          token_type="Bearer", expires_in=ACCESS_TTL,
                          refresh_token="r." + sign("refresh", claims, REFRESH_TTL),
                          scope=" ".join(scopes))

    async def exchange_authorization_code(self, client, authorization_code: AuthorizationCode) -> OAuthToken:
        now = time.time()
        self.used_codes = {c: t for c, t in self.used_codes.items() if t > now}
        self.used_codes[authorization_code.code] = authorization_code.expires_at
        return self._tokens(client.client_id, authorization_code.scopes, authorization_code.resource)

    async def load_refresh_token(self, client, refresh_token: str):
        data = verify("refresh", refresh_token[2:]) if refresh_token.startswith("r.") else None
        if not data or data["cid"] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, client_id=data["cid"], scopes=data["sc"],
                            expires_at=data["exp"], resource=data.get("res"))

    async def exchange_refresh_token(self, client, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        return self._tokens(client.client_id, scopes or refresh_token.scopes, refresh_token.resource)

    async def load_access_token(self, token: str) -> AccessToken | None:
        data = verify("access", token[2:]) if token.startswith("a.") else None
        if not data:
            return None
        return AccessToken(token=token, client_id=data["cid"], scopes=data["sc"],
                           expires_at=data["exp"], resource=data.get("res"))

    async def revoke_token(self, token) -> None:
        # Stateless tokens expire on their own; rotate SECRET_KEY to revoke everything.
        return None


provider = OwnerOAuthProvider()


# ---------------------------------------------------------------- login page
def _login_form(req: str, app_name: str, error: str = "") -> HTMLResponse:
    who = html.escape(app_name or "ИИ-приложение")
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return page("Доступ к Telegram", f"""<p><b>{who}</b> просит доступ к вашему Telegram:
читать чаты, отправлять сообщения и ставить отложенные посты.</p>{err}
<form method="post"><input type="hidden" name="req" value="{html.escape(req)}">
<input type="password" name="password" placeholder="Пароль сервера" autofocus required>
<button>Разрешить</button></form>
<p class="muted">Это пароль, который вы задали в ADMIN_PASSWORD на Render. Не вводите его, если не вы начали подключение.</p>""")


async def login_page(request: Request):
    req = request.query_params.get("req", "")
    data = verify("authreq", req)
    if not data:
        return page("Ссылка устарела", "<p>Начните подключение заново в приложении.</p>")
    return _login_form(req, data["name"])


async def login_submit(request: Request):
    form = await request.form()
    req, password = str(form.get("req", "")), str(form.get("password", ""))
    data = verify("authreq", req)
    if not data:
        return page("Ссылка устарела", "<p>Начните подключение заново в приложении.</p>")
    error = await guard.check(password)
    if error:
        return _login_form(req, data["name"], error)
    code = sign("code", {k: data[k] for k in ("cid", "ru", "rue", "cc", "sc", "res")}, CODE_TTL)
    return RedirectResponse(construct_redirect_uri(data["ru"], code=code, state=data["st"]),
                            status_code=302)
