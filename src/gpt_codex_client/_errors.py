from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class CodexError(Exception):
    """Base exception for this package."""


class AuthError(CodexError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass
class APIError(CodexError):
    message: str
    status_code: int
    body: Any | None = None
    retry_after: float | None = None

    def __str__(self) -> str:
        return self.message


class RateLimitError(APIError):
    pass


class APITimeoutError(CodexError):
    pass


class APIConnectionError(CodexError):
    pass


class InvalidRequestError(APIError):
    pass


class ServerError(APIError):
    pass


class StreamError(CodexError):
    pass


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _body(response: httpx.Response) -> Any | None:
    try:
        return response.json()
    except ValueError:
        return response.text or None


def _message(response: httpx.Response, body: Any | None) -> str:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return str(error["message"])
        if isinstance(body.get("message"), str):
            return str(body["message"])
    return f"Request failed with status {response.status_code}"


def error_from_response(response: httpx.Response) -> CodexError:
    body = _body(response)
    message = _message(response, body)
    retry_after = _retry_after(response)
    status_code = response.status_code
    if status_code in {401, 403}:
        return AuthError(message, status_code=status_code, body=body)
    if status_code == 429:
        return RateLimitError(message, status_code, body, retry_after)
    if status_code >= 500:
        return ServerError(message, status_code, body, retry_after)
    return InvalidRequestError(message, status_code, body, retry_after)


def is_retryable_error(error: CodexError) -> bool:
    return isinstance(error, RateLimitError | ServerError)
