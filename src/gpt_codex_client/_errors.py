from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._types import Response

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
    def __init__(
        self,
        message: str,
        *,
        kind: str = "protocol",
        code: str | None = None,
        partial_response: Response | None = None,
        raw_event: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.partial_response = partial_response
        self.raw_event = raw_event


def _retry_after(response: httpx.Response) -> float | None:
    for header, divisor in (("retry-after-ms", 1000), ("retry-after", 1)):
        value = response.headers.get(header)
        if value is None:
            continue
        try:
            delay = float(value) / divisor
        except ValueError:
            if header != "retry-after":
                continue
            try:
                delay = parsedate_to_datetime(value).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                continue
        if math.isfinite(delay):
            return max(0.0, delay)
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
    if not isinstance(error, APIError):
        return False
    if error.status_code == 429:
        body = error.body if isinstance(error.body, dict) else {}
        detail = body.get("error", body)
        code = str(detail.get("code", "")) if isinstance(detail, dict) else ""
        if re.search(
            r"insufficient_quota|usage_limit|quota_exceeded|billing|out of budget|quota exceeded|"
            r"available balance|monthly usage limit|GoUsageLimitError|FreeUsageLimitError",
            code + " " + error.message,
            re.I,
        ):
            return False
    return error.status_code in {408, 429, 500, 502, 503, 504}


def retry_delay(attempt: int, error: CodexError, maximum: float) -> float:
    delay = error.retry_after if isinstance(error, APIError) else None
    delay = delay if delay is not None else min(2.0, 0.25 * (2**attempt))
    if delay > maximum:
        if isinstance(error, APIError):
            error.message += f" (retry delay {delay}s exceeds max_retry_delay={maximum}s)"
        raise error
    return delay
