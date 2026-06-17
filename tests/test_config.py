from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from gpt_codex_client import AuthError, Token, build_headers, get_account_id
from gpt_codex_client._config import load_token, save_token


def test_token_save_permissions_and_load(tmp_path: Path) -> None:
    token_path = tmp_path / "auth.json"
    token = Token(access_token="access", refresh_token="refresh", expires_at=time.time() + 60)

    save_token(token, token_path)

    mode = os.stat(token_path).st_mode & 0o777
    assert mode == 0o600
    loaded = load_token(token_path)
    assert loaded is not None
    assert loaded.access_token == "access"
    assert loaded.refresh_token == "refresh"


def test_invalid_token_json_raises_auth_error(tmp_path: Path) -> None:
    token_path = tmp_path / "auth.json"
    token_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(AuthError):
        load_token(token_path)


def test_jwt_account_id_and_headers() -> None:
    access_token = _jwt({"account_id": "acct_123"})

    assert get_account_id(access_token) == "acct_123"

    headers = build_headers(access_token, default_headers={"x-extra": "yes"})
    assert headers["authorization"] == f"Bearer {access_token}"
    assert headers["chatgpt-account-id"] == "acct_123"
    assert headers["openai-beta"] == "responses=v1"
    assert headers["originator"] == "gpt-codex-client"
    assert headers["x-extra"] == "yes"


def _jwt(payload: dict[str, Any]) -> str:
    header = {"alg": "none", "typ": "JWT"}
    return ".".join([_b64(header), _b64(payload), ""])


def _b64(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
