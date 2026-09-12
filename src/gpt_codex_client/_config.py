from __future__ import annotations

import base64
import contextlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ._errors import AuthError

DEFAULT_BASE_URL = "https://chatgpt.com/backend-api/codex"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
DEFAULT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CLIENT_ID_ENV_VAR = "GPT_CODEX_CLIENT_OAUTH_CLIENT_ID"
DEFAULT_SCOPES = ("openid", "profile", "email", "offline_access")
DEFAULT_TOKEN_PATH = Path("~/.codex/auth.json")
DEFAULT_CLIENT_VERSION = "0.1.0"
CLIENT_VERSION_ENV_VAR = "GPT_CODEX_CLIENT_VERSION"
DEFAULT_MODELS_MANIFEST_URL = (
    "https://raw.githubusercontent.com/openai/codex/main/codex-rs/models-manager/models.json"
)
MODELS_MANIFEST_URL_ENV_VAR = "GPT_CODEX_CLIENT_MODELS_MANIFEST_URL"
USER_AGENT = "gpt-codex-client/0.1.0"
ORIGINATOR = "gpt-codex-client"
BETA_HEADER = "responses=v1"
DEFAULT_REDIRECT_URI = "http://localhost:1455/auth/callback"


@dataclass
class Token:
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None
    token_type: str = "Bearer"
    scope: str | None = None
    id_token: str | None = None
    account_id: str | None = None
    raw: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Token:
        token_payload = payload.get("tokens")
        if isinstance(token_payload, dict):
            payload = {**token_payload, **{k: v for k, v in payload.items() if k != "tokens"}}

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise AuthError("Token cache does not contain an access_token")

        expires_at = _expires_at(payload)
        refresh_token = payload.get("refresh_token")
        account_id = payload.get("account_id")
        token = cls(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            expires_at=expires_at,
            token_type=str(payload.get("token_type", "Bearer")),
            scope=payload.get("scope") if isinstance(payload.get("scope"), str) else None,
            id_token=payload.get("id_token") if isinstance(payload.get("id_token"), str) else None,
            account_id=account_id if isinstance(account_id, str) else None,
            raw=payload,
        )
        if token.account_id is None:
            token.account_id = get_account_id(token.access_token)
        return token

    def is_expired(self, *, skew_seconds: float = 60.0) -> bool:
        return self.expires_at is not None and self.expires_at <= time.time() + skew_seconds

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        raw = payload.pop("raw", None)
        if isinstance(raw, dict):
            for key, value in raw.items():
                payload.setdefault(key, value)
        return {key: value for key, value in payload.items() if value is not None}


def _expires_at(payload: dict[str, Any]) -> float | None:
    expires_at = payload.get("expires_at")
    if isinstance(expires_at, int | float):
        return float(expires_at)
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, int | float):
        return time.time() + float(expires_in) - 30.0
    return None


def expand_token_path(token_path: str | Path) -> Path:
    return Path(token_path).expanduser()


def get_client_id(client_id: str | None = None) -> str:
    resolved = client_id or os.environ.get(CLIENT_ID_ENV_VAR) or DEFAULT_CLIENT_ID
    if not resolved.strip():
        raise AuthError("OAuth client_id cannot be empty")
    return resolved


def get_client_version(client_version: str | None = None) -> str:
    resolved = client_version or os.environ.get(CLIENT_VERSION_ENV_VAR) or DEFAULT_CLIENT_VERSION
    if not resolved.strip():
        raise AuthError("client_version cannot be empty")
    return resolved


def get_models_manifest_url(models_manifest_url: str | None = None) -> str:
    resolved = (
        models_manifest_url
        or os.environ.get(MODELS_MANIFEST_URL_ENV_VAR)
        or DEFAULT_MODELS_MANIFEST_URL
    )
    if not resolved.strip():
        raise AuthError("models manifest URL cannot be empty")
    return resolved


def load_token(token_path: str | Path = DEFAULT_TOKEN_PATH) -> Token | None:
    path = expand_token_path(token_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuthError(f"Invalid token cache JSON at {path}") from exc
    if not isinstance(payload, dict):
        raise AuthError(f"Invalid token cache shape at {path}")
    return Token.from_payload(payload)


def save_token(token: Token, token_path: str | Path = DEFAULT_TOKEN_PATH) -> None:
    path = expand_token_path(token_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(token.to_payload(), indent=2, sort_keys=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(data)
            file.write("\n")
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.chmod(path, 0o600)


def get_account_id(access_token: str) -> str | None:
    parts = access_token.split(".")
    if len(parts) < 2:
        return None
    payload_segment = parts[1]
    padding = "=" * (-len(payload_segment) % 4)
    try:
        raw = base64.urlsafe_b64decode(f"{payload_segment}{padding}")
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    auth_claim = payload.get("https://api.openai.com/auth")
    if isinstance(auth_claim, dict):
        account = auth_claim.get("chatgpt_account_id") or auth_claim.get("account_id")
        if isinstance(account, str):
            return account

    for key in ("chatgpt_account_id", "account_id", "org_id"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return None


def build_headers(
    token: str | Token,
    *,
    default_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    access_token = token.access_token if isinstance(token, Token) else token
    account_id = token.account_id if isinstance(token, Token) else get_account_id(access_token)
    headers = {
        "authorization": f"Bearer {access_token}",
        "content-type": "application/json",
        "accept": "application/json",
        "user-agent": USER_AGENT,
        "openai-beta": BETA_HEADER,
        "originator": ORIGINATOR,
    }
    if account_id:
        headers["chatgpt-account-id"] = account_id
    if default_headers:
        headers.update(default_headers)
    return headers
