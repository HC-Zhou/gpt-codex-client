from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from ._auth import (
    LoginHandler,
    PendingLogin,
    _code_from_callback,
    _token_from_response,
    start_login,
)
from ._config import CLIENT_ID, DEFAULT_TOKEN_PATH, TOKEN_URL, Token, load_token, save_token
from ._errors import AuthError


async def afinish_login(
    callback_url: str,
    pending: PendingLogin,
    *,
    token_path: str | Path = DEFAULT_TOKEN_PATH,
    http_client: httpx.AsyncClient | None = None,
    timeout: float | httpx.Timeout | None = 120.0,
) -> Token:
    code = _code_from_callback(callback_url, pending.state)
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await client.post(
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
            await client.aclose()


async def alogin(
    *,
    headless: bool = False,
    no_browser: bool = False,
    token_path: str | Path = DEFAULT_TOKEN_PATH,
    login_handler: LoginHandler | None = None,
    http_client: httpx.AsyncClient | None = None,
    timeout: float | httpx.Timeout | None = 120.0,
) -> Token:
    if login_handler is not None:
        pending = start_login()
        callback_url = login_handler(pending.url)
        return await afinish_login(
            callback_url,
            pending,
            token_path=token_path,
            http_client=http_client,
            timeout=timeout,
        )

    from ._auth import login

    def run_sync_login() -> Token:
        return login(
            headless=headless,
            no_browser=no_browser,
            token_path=token_path,
            login_handler=None,
            timeout=timeout,
        )

    return await asyncio.to_thread(run_sync_login)


async def arefresh(
    *,
    token_path: str | Path = DEFAULT_TOKEN_PATH,
    refresh_token: str | None = None,
    http_client: httpx.AsyncClient | None = None,
    timeout: float | httpx.Timeout | None = 120.0,
) -> Token:
    cached = load_token(token_path)
    resolved_refresh_token = refresh_token or (cached.refresh_token if cached is not None else None)
    if not resolved_refresh_token:
        raise AuthError("No refresh token is available")

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await client.post(
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
            await client.aclose()


async def aget_token(
    *,
    token_path: str | Path = DEFAULT_TOKEN_PATH,
    headless: bool = False,
    no_browser: bool = False,
    login_handler: LoginHandler | None = None,
    http_client: httpx.AsyncClient | None = None,
    timeout: float | httpx.Timeout | None = 120.0,
) -> Token:
    cached = load_token(token_path)
    if cached is not None and not cached.is_expired():
        return cached

    if cached is not None and cached.refresh_token:
        try:
            return await arefresh(
                token_path=token_path,
                refresh_token=cached.refresh_token,
                http_client=http_client,
                timeout=timeout,
            )
        except AuthError:
            pass

    return await alogin(
        headless=headless,
        no_browser=no_browser,
        token_path=token_path,
        login_handler=login_handler,
        http_client=http_client,
        timeout=timeout,
    )


def _unused(value: Any) -> None:
    return None
