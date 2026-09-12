from __future__ import annotations

import asyncio
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.parse import urljoin

import httpx

from ._async_auth import aget_token
from ._async_models import AsyncModelsResource
from ._async_responses import AsyncResponsesResource
from ._async_stream import AsyncResponseStream
from ._auth import LoginHandler
from ._chat import AsyncChatResource
from ._config import (
    DEFAULT_BASE_URL,
    DEFAULT_TOKEN_PATH,
    Token,
    build_headers,
    get_client_version,
)
from ._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    CodexError,
    error_from_response,
    is_retryable_error,
)
from ._types import JsonObject


class AsyncCodexClient:
    def __init__(
        self,
        *,
        headless: bool = False,
        no_browser: bool = False,
        token_path: str | Path = DEFAULT_TOKEN_PATH,
        login_handler: LoginHandler | None = None,
        auth_client_id: str | None = None,
        client_version: str | None = None,
        models_manifest_url: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 2,
        default_headers: dict[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self.headless = headless
        self.no_browser = no_browser
        self.token_path = token_path
        self.login_handler = login_handler
        self.auth_client_id = auth_client_id
        self.client_version = get_client_version(client_version)
        self.models_manifest_url = models_manifest_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.default_headers = default_headers or {}
        self.base_url = base_url.rstrip("/") + "/"
        self._http_client = http_client or httpx.AsyncClient(timeout=timeout)
        self._owns_http_client = http_client is None
        self._token: Token | None = None

        self.responses = AsyncResponsesResource(self)
        self.chat = AsyncChatResource(self)
        self.models = AsyncModelsResource(self, manifest_url=models_manifest_url)

    async def __aenter__(self) -> AsyncCodexClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: JsonObject | None = None,
        timeout: float | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> JsonObject:
        url = urljoin(self.base_url, path.lstrip("/"))
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                response = await self._http_client.request(
                    method,
                    url,
                    json=json,
                    params=self._params(),
                    headers=await self._headers(extra_headers),
                    timeout=timeout or self.timeout,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 < attempts:
                    await self._sleep_before_retry(attempt, None)
                    continue
                raise APITimeoutError(str(exc)) from exc
            except httpx.RequestError as exc:
                if attempt + 1 < attempts:
                    await self._sleep_before_retry(attempt, None)
                    continue
                raise APIConnectionError(str(exc)) from exc

            if response.status_code < 400:
                return _json_object(response)
            error = error_from_response(response)
            if attempt + 1 < attempts and is_retryable_error(error):
                retry_after = error.retry_after if isinstance(error, APIError) else None
                await self._sleep_before_retry(attempt, retry_after)
                continue
            raise error
        raise APIConnectionError("Request retry loop exited unexpectedly")

    async def _stream(
        self,
        method: str,
        path: str,
        *,
        json: JsonObject | None = None,
        timeout: float | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> AsyncResponseStream:
        url = urljoin(self.base_url, path.lstrip("/"))
        manager = self._http_client.stream(
            method,
            url,
            json=json,
            params=self._params(),
            headers=await self._headers(extra_headers),
            timeout=timeout or self.timeout,
        )
        return AsyncResponseStream(manager)

    def _params(self) -> dict[str, str]:
        return {"client_version": self.client_version}

    async def _headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        token = self._token
        if token is None or token.is_expired():
            token = await aget_token(
                token_path=self.token_path,
                headless=self.headless,
                no_browser=self.no_browser,
                login_handler=self.login_handler,
                client_id=self.auth_client_id,
                http_client=self._http_client,
                timeout=self.timeout,
            )
            self._token = token
        headers = build_headers(token, default_headers=self.default_headers)
        if extra_headers:
            headers.update(extra_headers)
        return headers

    async def _sleep_before_retry(self, attempt: int, retry_after: float | None) -> None:
        delay = retry_after if retry_after is not None else min(2.0, 0.25 * (2**attempt))
        await asyncio.sleep(delay)


def _json_object(response: httpx.Response) -> JsonObject:
    if not response.content:
        return {}
    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise CodexError("Response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise CodexError("Response JSON was not an object")
    return payload
