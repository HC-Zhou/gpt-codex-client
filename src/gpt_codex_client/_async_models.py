from __future__ import annotations

import time
from typing import Any

import httpx

from ._config import get_models_manifest_url
from ._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    CodexError,
    error_from_response,
    is_retryable_error,
)
from ._models import _models_from_payload
from ._types import JsonObject, Model


class AsyncModelsResource:
    def __init__(
        self,
        client: Any,
        *,
        ttl_seconds: float = 300.0,
        manifest_url: str | None = None,
    ) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds
        self._manifest_url = get_models_manifest_url(manifest_url)
        self._cache: list[Model] | None = None
        self._cache_at = 0.0

    async def list(
        self, *, force_refresh: bool = False, timeout: float | None = None
    ) -> list[Model]:
        if (
            not force_refresh
            and self._cache is not None
            and time.time() - self._cache_at < self._ttl_seconds
        ):
            return list(self._cache)
        payload = await self._fetch_manifest(timeout=timeout)
        models = _models_from_payload(payload)
        self._cache = models
        self._cache_at = time.time()
        return list(models)

    async def _fetch_manifest(self, *, timeout: float | None = None) -> JsonObject:
        attempts = self._client.max_retries + 1
        for attempt in range(attempts):
            try:
                response = await self._client._http_client.get(
                    self._manifest_url,
                    headers={"accept": "application/json"},
                    timeout=timeout or self._client.timeout,
                )
            except httpx.TimeoutException as exc:
                if attempt + 1 < attempts:
                    await self._client._sleep_before_retry(attempt, None)
                    continue
                raise APITimeoutError(str(exc)) from exc
            except httpx.RequestError as exc:
                if attempt + 1 < attempts:
                    await self._client._sleep_before_retry(attempt, None)
                    continue
                raise APIConnectionError(str(exc)) from exc
            if response.status_code < 400:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise CodexError("Models manifest response was not valid JSON") from exc
                if not isinstance(payload, dict):
                    raise CodexError("Models manifest JSON was not an object")
                return payload
            error = error_from_response(response)
            if attempt + 1 < attempts and is_retryable_error(error):
                retry_after = error.retry_after if isinstance(error, APIError) else None
                await self._client._sleep_before_retry(attempt, retry_after)
                continue
            raise error
        raise APIConnectionError("Models manifest retry loop exited unexpectedly")
