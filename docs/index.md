# Getting Started

`gpt-codex-client` provides a typed Python client with an OpenAI SDK-style
surface:

```python
from gpt_codex_client import CodexClient

client = CodexClient()
models = client.models.list()
response = client.responses.create(
    model=models[0].id,
    input="Write a compact project summary.",
)
print(response.output_text)
```

This package targets ChatGPT/Codex OAuth-backed backend behavior, not standard
API-key access to `api.openai.com`.

