from __future__ import annotations

import hashlib


def session_header(session_id: str | None) -> str | None:
    if session_id is None:
        return None
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id must be a non-blank string")
    return (
        session_id
        if len(session_id) <= 64
        else hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    )


def cache_key(session_id: str | None, prompt_cache_key: str | None) -> str | None:
    default = session_header(session_id)
    if prompt_cache_key is None:
        return default
    if (
        not isinstance(prompt_cache_key, str)
        or not prompt_cache_key.strip()
        or len(prompt_cache_key) > 64
    ):
        raise ValueError(
            "prompt_cache_key must contain 1 to 64 Unicode characters and not be blank"
        )
    return prompt_cache_key


def session_headers(headers: dict[str, str], session_id: str | None) -> dict[str, str]:
    result = {k.lower(): v for k, v in headers.items()}
    value = session_header(session_id)
    if value is not None:
        result.update({"session-id": value, "x-client-request-id": value})
    return result
