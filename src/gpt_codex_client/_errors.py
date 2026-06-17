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
        if isinstance(body.get("detail"), str):
            return str(body["detail"])
        if isinstance(body.get("detail"), list):
            return _message_from_validation_errors(body["detail"], response.status_code)
    if isinstance(body, list):
        return _message_from_validation_errors(body, response.status_code)
    return f"Request failed with status {response.status_code}"


def _message_from_validation_errors(errors: list[Any], status_code: int) -> str:
    messages: list[str] = []
    for error in errors:
        if not isinstance(error, dict):
            continue
        message = error.get("msg")
        location = error.get("loc")
        if isinstance(message, str):
            if isinstance(location, list | tuple) and location:
                messages.append(f"{'.'.join(str(part) for part in location)}: {message}")
            else:
                messages.append(message)
    if messages:
        return "; ".join(messages)
    return f"Request failed with status {status_code}"


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
