from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import urllib.parse
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import httpx

from ._config import (
    AUTHORIZE_URL,
    CLIENT_ID,
    DEFAULT_SCOPES,
    DEFAULT_TOKEN_PATH,
    TOKEN_URL,
    Token,
    load_token,
    save_token,
)
from ._errors import AuthError

LoginHandler = Callable[[str], str]


@dataclass(frozen=True)
class PendingLogin:
    url: str
    state: str
    verifier: str
    redirect_uri: str


def make_pkce_verifier() -> str:
    return secrets.token_urlsafe(64)[:96]


def make_pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def start_login(
    *,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
    redirect_uri: str | None = None,
) -> PendingLogin:
    state = secrets.token_urlsafe(32)
    verifier = make_pkce_verifier()
    challenge = make_pkce_challenge(verifier)
    resolved_redirect_uri = redirect_uri or _loopback_redirect_uri()
    query = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": resolved_redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(query)}"
    return PendingLogin(url=url, state=state, verifier=verifier, redirect_uri=resolved_redirect_uri)


def finish_login(
    callback_url: str,
    pending: PendingLogin,
    *,
    token_path: str | Path = DEFAULT_TOKEN_PATH,
    http_client: httpx.Client | None = None,
    timeout: float | httpx.Timeout | None = 120.0,
) -> Token:
    code = _code_from_callback(callback_url, pending.state)
    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=timeout)
    try:
        response = client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "redirect_uri": pending.redirect_uri,
                "code_verifier": pending.verifier,
            },
            timeout=timeout,
        )
        token = _token_from_response(response)
        save_token(token, token_path)
        return token
    finally:
        if owns_client:
            client.close()


def login(
    *,
    headless: bool = False,
    no_browser: bool = False,
    token_path: str | Path = DEFAULT_TOKEN_PATH,
    login_handler: LoginHandler | None = None,
    http_client: httpx.Client | None = None,
    timeout: float | httpx.Timeout | None = 120.0,
) -> Token:
    pending = start_login()
    if login_handler is not None:
        callback_url = login_handler(pending.url)
    elif headless:
        print(f"Open this URL to authorize gpt-codex-client:\n{pending.url}")
        callback_url = input("Paste the final redirect URL: ").strip()
    else:
        if no_browser:
            print(f"Open this URL to authorize gpt-codex-client:\n{pending.url}")
        else:
            webbrowser.open(pending.url)
        callback_url = _wait_for_callback(pending)
    return finish_login(
        callback_url,
        pending,
        token_path=token_path,
        http_client=http_client,
        timeout=timeout,
    )


def refresh(
    *,
    token_path: str | Path = DEFAULT_TOKEN_PATH,
    refresh_token: str | None = None,
    http_client: httpx.Client | None = None,
    timeout: float | httpx.Timeout | None = 120.0,
) -> Token:
    cached = load_token(token_path)
    resolved_refresh_token = refresh_token or (cached.refresh_token if cached is not None else None)
    if not resolved_refresh_token:
        raise AuthError("No refresh token is available")

    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=timeout)
    try:
        response = client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": resolved_refresh_token,
            },
            timeout=timeout,
        )
        token = _token_from_response(response)
        if token.refresh_token is None:
            token.refresh_token = resolved_refresh_token
        save_token(token, token_path)
        return token
    finally:
        if owns_client:
            client.close()


def get_token(
    *,
    token_path: str | Path = DEFAULT_TOKEN_PATH,
    headless: bool = False,
    no_browser: bool = False,
    login_handler: LoginHandler | None = None,
    http_client: httpx.Client | None = None,
    timeout: float | httpx.Timeout | None = 120.0,
) -> Token:
    cached = load_token(token_path)
    if cached is not None and not cached.is_expired():
        return cached

    if cached is not None and cached.refresh_token:
        try:
            return refresh(
                token_path=token_path,
                refresh_token=cached.refresh_token,
                http_client=http_client,
                timeout=timeout,
            )
        except AuthError:
            pass

    return login(
        headless=headless,
        no_browser=no_browser,
        token_path=token_path,
        login_handler=login_handler,
        http_client=http_client,
        timeout=timeout,
    )


def _token_from_response(response: httpx.Response) -> Token:
    if response.status_code >= 400:
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        raise AuthError("OAuth token exchange failed", status_code=response.status_code, body=body)
    try:
        payload = response.json()
    except ValueError as exc:
        raise AuthError("OAuth token endpoint returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise AuthError("OAuth token endpoint returned an invalid payload")
    return Token.from_payload(payload)


def _code_from_callback(callback_url: str, expected_state: str) -> str:
    parsed = urllib.parse.urlparse(callback_url)
    values = urllib.parse.parse_qs(parsed.query)
    error = _first(values, "error")
    if error:
        description = _first(values, "error_description") or error
        raise AuthError(f"OAuth callback returned an error: {description}")
    state = _first(values, "state")
    if state != expected_state:
        raise AuthError("OAuth callback state did not match the login session")
    code = _first(values, "code")
    if not code:
        raise AuthError("OAuth callback did not include a code")
    return code


def _first(values: dict[str, list[str]], key: str) -> str | None:
    value = values.get(key)
    if not value:
        return None
    return value[0]


def _loopback_redirect_uri() -> str:
    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_port
    server.server_close()
    return f"http://127.0.0.1:{port}/callback"


def _wait_for_callback(pending: PendingLogin) -> str:
    parsed = urllib.parse.urlparse(pending.redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    path = parsed.path or "/callback"
    if port is None:
        raise AuthError("Loopback redirect URI must include a port")

    result: dict[str, str] = {}
    ready = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request_url = f"http://{self.headers.get('host', f'{host}:{port}')}{self.path}"
            request_path = urllib.parse.urlparse(request_url).path
            if request_path != path:
                self.send_response(404)
                self.end_headers()
                return
            result["url"] = request_url
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body>Login complete. You can close this tab.</body></html>")
            ready.set()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer((host, port), Handler)
    try:
        while not ready.is_set():
            server.handle_request()
    finally:
        server.server_close()
    return result["url"]
