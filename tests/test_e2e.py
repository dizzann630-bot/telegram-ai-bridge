"""End-to-end test of the OAuth login and MCP over HTTP (no Telegram network needed).

Run: python -m pytest tests -q   (starts the real server with uvicorn twice)
"""
import base64
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

PASSWORD = "correct-horse-battery"
REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, secret_key):
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        env = {**os.environ, "SECRET_KEY": secret_key, "ADMIN_PASSWORD": PASSWORD,
               "TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "test", "PUBLIC_URL": self.url}
        env.pop("TELEGRAM_SESSION", None)
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.server:app",
                                      "--port", str(self.port), "--log-level", "warning"],
                                     env=env, cwd=os.path.dirname(os.path.dirname(__file__)))
        for _ in range(100):
            try:
                if httpx.get(self.url + "/health").status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.1)
        raise RuntimeError("server did not start")

    def stop(self):
        self.proc.terminate()
        self.proc.wait(10)


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def mcp_call(url, token, method, params=None, id_=1):
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
               "MCP-Protocol-Version": "2025-06-18"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}
    return httpx.post(url + "/mcp", headers=headers, json=body, timeout=60)


def full_login(server):
    reg = httpx.post(server.url + "/register", json={
        "redirect_uris": [REDIRECT], "client_name": "ChatGPT", "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], "token_endpoint_auth_method": "client_secret_post"}).json()
    verifier, challenge = pkce()
    r = httpx.get(server.url + "/authorize", params={
        "response_type": "code", "client_id": reg["client_id"], "redirect_uri": REDIRECT,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz", "scope": "telegram"})
    assert r.status_code == 302
    login_url = r.headers["location"]
    assert login_url.startswith(server.url + "/login?req=")
    return reg, verifier, login_url


@pytest.fixture(scope="module")
def secret_key():
    return secrets.token_hex(32)


@pytest.fixture(scope="module")
def server(secret_key):
    s = Server(secret_key)
    yield s
    s.stop()


def test_metadata(server):
    meta = httpx.get(server.url + "/.well-known/oauth-authorization-server").json()
    assert meta["registration_endpoint"].endswith("/register")
    assert "S256" in meta["code_challenge_methods_supported"]
    prm = httpx.get(server.url + "/.well-known/oauth-protected-resource/mcp").json()
    assert prm["resource"] == server.url + "/mcp"


def test_mcp_requires_token(server):
    r = mcp_call(server.url, None, "tools/list")
    assert r.status_code == 401
    assert "resource_metadata" in r.headers.get("www-authenticate", "")
    assert mcp_call(server.url, "a.forged.token", "tools/list").status_code == 401


def test_wrong_password_is_rejected(server):
    _, _, login_url = full_login(server)
    req = parse_qs(urlparse(login_url).query)["req"][0]
    r = httpx.post(server.url + "/login", data={"req": req, "password": "wrong-password"})
    assert r.status_code == 200 and "Неверный пароль" in r.text


def test_upload_link_validation(server):
    assert httpx.post(server.url + "/upload?t=bad", files={"file": ("a.png", b"x")}).status_code == 403


def test_setup_requires_password(server):
    r = httpx.post(server.url + "/setup", data={"password": "nope"})
    assert "Неверный пароль" in r.text or "Слишком много" in r.text


def test_full_flow_and_restart(secret_key, server):
    reg, verifier, login_url = full_login(server)
    assert "ChatGPT" in httpx.get(login_url).text
    req = parse_qs(urlparse(login_url).query)["req"][0]
    r = httpx.post(server.url + "/login", data={"req": req, "password": PASSWORD})
    assert r.status_code == 302
    back = urlparse(r.headers["location"])
    assert f"{back.scheme}://{back.netloc}{back.path}" == REDIRECT
    q = parse_qs(back.query)
    assert q["state"] == ["xyz"]
    code = q["code"][0]

    token_req = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                 "client_id": reg["client_id"], "client_secret": reg["client_secret"], "code_verifier": verifier}
    bad = httpx.post(server.url + "/token", data={**token_req, "code_verifier": "x" * 50})
    assert bad.status_code == 400  # PKCE mismatch
    tokens = httpx.post(server.url + "/token", data=token_req).json()
    assert tokens["token_type"].lower() == "bearer"
    replay = httpx.post(server.url + "/token", data=token_req)
    assert replay.status_code == 400  # code is single-use

    access = tokens["access_token"]
    init = mcp_call(server.url, access, "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    assert init.status_code == 200, init.text
    tools = mcp_call(server.url, access, "tools/list").json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"list_chats", "send_message", "schedule_post", "attach_chatgpt_files"} <= names
    fileparam = next(t for t in tools if t["name"] == "attach_chatgpt_files")
    assert fileparam["_meta"]["openai/fileParams"] == ["files"]

    call = mcp_call(server.url, access, "tools/call", {"name": "whoami", "arguments": {}}).json()["result"]
    assert call["isError"] and "/setup" in call["content"][0]["text"]  # no Telegram session yet

    link = mcp_call(server.url, access, "tools/call", {"name": "get_upload_link", "arguments": {}}).json()
    upload_link = json.loads(link["result"]["content"][0]["text"])["link"]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    up = httpx.post(upload_link, files={"file": ("cat.png", png, "image/png")}).json()
    assert up["uploads"][0]["kind"] == "png"
    listed = mcp_call(server.url, access, "tools/call", {"name": "list_uploads", "arguments": {}}).json()
    assert up["uploads"][0]["id"] in listed["result"]["content"][0]["text"]

    # Restart with the same SECRET_KEY: client, access and refresh tokens still work.
    server.stop()
    again = Server(secret_key)
    try:
        assert mcp_call(again.url, access, "tools/list").status_code == 200
        refreshed = httpx.post(again.url + "/token", data={
            "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
            "client_id": reg["client_id"], "client_secret": reg["client_secret"]})
        assert refreshed.status_code == 200, refreshed.text
        assert mcp_call(again.url, refreshed.json()["access_token"], "tools/list").status_code == 200
    finally:
        again.stop()
    # A different SECRET_KEY invalidates everything (that is the "log everyone out" switch).
    other = Server(secrets.token_hex(32))
    try:
        assert mcp_call(other.url, access, "tools/list").status_code == 401
    finally:
        other.stop()
    server.proc = subprocess.Popen(["true"])  # fixture teardown no-op
