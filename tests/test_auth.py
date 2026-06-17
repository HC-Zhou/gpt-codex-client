from __future__ import annotations

import time
import urllib.parse
from pathlib import Path

import httpx
import pytest

from gpt_codex_client import AuthError, PendingLogin, finish_login, get_token, refresh, start_login
from gpt_codex_client._auth import make_pkce_challenge, make_pkce_verifier
from gpt_codex_client._config import Token, load_token, save_token


def test_pkce_verifier_and_challenge_shape() -> None:
    verifier = make_pkce_verifier()
    challenge = make_pkce_challenge(verifier)

    assert 43 <= len(verifier) <= 128
    assert len(challenge) == 43
    assert "=" not in challenge


def test_finish_login_validates_state(tmp_path: Path) -> None:
    pending = PendingLogin(
        url="https://example.test",
        state="expected",
        verifier="verifier",
        redirect_uri="http://127.0.0.1/callback",
    )

    with pytest.raises(AuthError):
        finish_login(
            "http://127.0.0.1/callback?state=wrong&code=abc",
            pending,
            token_path=tmp_path / "auth.json",
        )


def test_finish_login_exchanges_code_and_saves_token(tmp_path: Path) -> None:
    token_path = tmp_path / "auth.json"
    pending = PendingLogin(
        url="https://example.test",
        state="state",
        verifier="verifier",
        redirect_uri="http://127.0.0.1/callback",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/token"
        body = urllib.parse.parse_qs(request.content.decode("utf-8"))
        assert body["grant_type"] == ["authorization_code"]
        assert body["code"] == ["abc"]
        assert body["code_verifier"] == ["verifier"]
        return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    token = finish_login(
        "http://127.0.0.1/callback?state=state&code=abc",
        pending,
        token_path=token_path,
        http_client=client,
    )

    assert token.access_token == "access"
    cached = load_token(token_path)
    assert cached is not None
    assert cached.refresh_token == "refresh"
    client.close()


def test_refresh_uses_cached_refresh_token(tmp_path: Path) -> None:
    token_path = tmp_path / "auth.json"
    save_token(Token(access_token="old", refresh_token="refresh", expires_at=1), token_path)

    def handler(request: httpx.Request) -> httpx.Response:
        body = urllib.parse.parse_qs(request.content.decode("utf-8"))
        assert body["grant_type"] == ["refresh_token"]
        assert body["refresh_token"] == ["refresh"]
        return httpx.Response(200, json={"access_token": "new", "expires_in": 3600})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    token = refresh(token_path=token_path, http_client=client)

    assert token.access_token == "new"
    assert token.refresh_token == "refresh"
    client.close()


def test_get_token_cache_hit(tmp_path: Path) -> None:
    token_path = tmp_path / "auth.json"
    save_token(Token(access_token="cached", expires_at=time.time() + 3600), token_path)

    assert get_token(token_path=token_path).access_token == "cached"


def test_expired_token_refresh_fallback_to_login(tmp_path: Path) -> None:
    token_path = tmp_path / "auth.json"
    save_token(Token(access_token="old", refresh_token="refresh", expires_at=1), token_path)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = urllib.parse.parse_qs(request.content.decode("utf-8"))
        grant_type = body["grant_type"][0]
        calls.append(grant_type)
        if grant_type == "refresh_token":
            return httpx.Response(400, json={"error": {"message": "bad refresh"}})
        return httpx.Response(
            200, json={"access_token": "from-login", "refresh_token": "new-refresh"}
        )

    def login_handler(url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        values = urllib.parse.parse_qs(parsed.query)
        redirect_uri = values["redirect_uri"][0]
        state = values["state"][0]
        return f"{redirect_uri}?state={state}&code=login-code"

    client = httpx.Client(transport=httpx.MockTransport(handler))
    token = get_token(token_path=token_path, http_client=client, login_handler=login_handler)

    assert calls == ["refresh_token", "authorization_code"]
    assert token.access_token == "from-login"
    client.close()


def test_start_login_url_contains_state_and_challenge() -> None:
    pending = start_login(redirect_uri="http://127.0.0.1:1234/callback")
    values = urllib.parse.parse_qs(urllib.parse.urlparse(pending.url).query)

    assert values["state"] == [pending.state]
    assert values["code_challenge_method"] == ["S256"]
    assert values["redirect_uri"] == [pending.redirect_uri]
