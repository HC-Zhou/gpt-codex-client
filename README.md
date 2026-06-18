<p align="center">
  <img src="docs/assets/gpt-codex-client-icon.svg" width="132" alt="gpt-codex-client icon">
</p>

<h1 align="center">gpt-codex-client</h1>

<p align="center">
  <strong>OpenAI SDK-style Python client for ChatGPT/Codex OAuth-backed workflows.</strong>
</p>

<p align="center">
  English · <a href="README.zh-CN.md">简体中文</a> ·
  <a href="https://pypi.org/project/gpt-codex-client/">PyPI</a> ·
  <a href="https://hc-zhou.github.io/gpt-codex-client/">Docs</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/gpt-codex-client/"><img alt="PyPI" src="https://img.shields.io/pypi/v/gpt-codex-client?color=2563eb"></a>
  <a href="https://pypi.org/project/gpt-codex-client/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/gpt-codex-client?color=0891b2"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/HC-Zhou/gpt-codex-client?color=16a34a"></a>
  <a href="https://github.com/HC-Zhou/gpt-codex-client/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/HC-Zhou/gpt-codex-client/actions/workflows/ci.yml/badge.svg"></a>
</p>

`gpt-codex-client` is an OpenAI SDK-style Python client for ChatGPT/Codex
OAuth-backed workflows. It is intentionally not an API-key client for
`api.openai.com`; it uses a local token cache compatible with
`~/.codex/auth.json` and requires an account that can access the relevant
ChatGPT/Codex backend.

## Install

```bash
uv add gpt-codex-client
```

## Quick Start

```python
from gpt_codex_client import CodexClient

with CodexClient(no_browser=True) as client:
    response = client.responses.create(
        model="gpt-5.5",
        input="Write a short Python function that reverses a string.",
    )
    print(response.output_text)
```

## Highlights

- Responses-style sync and async clients with streaming support.
- Chat Completions compatibility for existing message/tool-call workflows.
- OAuth PKCE login, refresh tokens, and `~/.codex/auth.json` token cache support.
- Model discovery from the public OpenAI Codex model registry.
- Optional Pydantic parsing for structured output.

## List Models

`client.models.list()` reads the public OpenAI Codex model registry from the
`openai/codex` GitHub repository instead of the ChatGPT/Codex backend `/models`
endpoint.

```python
from gpt_codex_client import CodexClient

with CodexClient() as client:
    models = client.models.list()
    for model in models:
        print(model.id)
```

The registry source is:

```text
https://raw.githubusercontent.com/openai/codex/main/codex-rs/models-manager/models.json
```

Set `GPT_CODEX_CLIENT_MODELS_MANIFEST_URL` or pass `models_manifest_url=` to
use another compatible registry.

## Authentication

The client lazily authenticates on the first request. By default it reads and
writes `~/.codex/auth.json` with `0600` permissions.

```python
from gpt_codex_client import login

login(no_browser=True)
```

The default OAuth client id follows the ChatGPT/Codex sign-in flow used by the
official Codex clients. If OpenAI issues a different client id for your app, set
`GPT_CODEX_CLIENT_OAUTH_CLIENT_ID` or pass `auth_client_id=` to `CodexClient`.

For automation, pass a `login_handler` that receives the authorization URL and
returns the final redirect URL:

```python
from gpt_codex_client import login

token = login(login_handler=lambda url: input(f"Open {url}\nRedirect URL: "))
```

## Responses

```python
with CodexClient() as client:
    response = client.responses.create(
        model="gpt-5.5",
        input="Summarize this repository.",
        reasoning={"effort": "medium"},
        text={"verbosity": "low"},
    )
```

Streaming returns a context manager and iterator:

```python
with CodexClient() as client:
    with client.responses.create(model="gpt-5.5", input="Say hi", stream=True) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                print(event.data.get("delta"), end="")
```

## Structured Output

Install the optional extra when using Pydantic models:

```bash
uv add "gpt-codex-client[pydantic]"
```

```python
from pydantic import BaseModel
from gpt_codex_client import CodexClient

class Result(BaseModel):
    title: str

parsed = CodexClient().responses.parse(
    model="gpt-5.5",
    input="Return JSON with a title.",
    text_format=Result,
)
print(parsed.parsed.title)
```

## Chat Compatibility

The chat compatibility layer converts Chat Completions-style messages and
function tools into Responses requests:

```python
completion = CodexClient().chat.completions.create(
    model="gpt-5.5",
    messages=[{"role": "user", "content": "Hello"}],
)
print(completion.choices[0].message.content)
```

## Development

```bash
uv sync --all-extras --dev
uv run pytest -q
```
