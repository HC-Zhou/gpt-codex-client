# gpt-codex-client

`gpt-codex-client` is an OpenAI SDK-style Python client for ChatGPT/Codex
OAuth-backed workflows. It is intentionally not an API-key client for
`api.openai.com`; it uses a local token cache compatible with
`~/.codex/auth.json` and requires an account that can access the relevant
ChatGPT/Codex backend.

```bash
uv add gpt-codex-client
```

```python
from gpt_codex_client import CodexClient

with CodexClient(no_browser=True) as client:
    model = client.models.list()[0].id
    response = client.responses.create(
        model=model,
        input="Write a short Python function that reverses a string.",
    )
    print(response.output_text)
```

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
        model="model-from-client.models.list",
        input="Summarize this repository.",
        reasoning={"effort": "medium"},
        text={"verbosity": "low"},
    )
```

Streaming returns a context manager and iterator:

```python
with CodexClient() as client:
    with client.responses.create(model="model", input="Say hi", stream=True) as stream:
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
    model="model",
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
    model="model",
    messages=[{"role": "user", "content": "Hello"}],
)
print(completion.choices[0].message.content)
```

## Development

```bash
uv sync --all-extras --dev
uv run pytest -q
```
