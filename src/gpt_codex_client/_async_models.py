from __future__ import annotations

import time
from typing import Any

from ._models import _models_from_payload
from ._types import Model


class AsyncModelsResource:
    def __init__(self, client: Any, *, ttl_seconds: float = 300.0) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds
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
        payload = await self._client._request("GET", "/models", timeout=timeout)
        models = _models_from_payload(payload)
        self._cache = models
        self._cache_at = time.time()
        return list(models)
