# Structured Output

Install the optional Pydantic extra:

```bash
uv add "gpt-codex-client[pydantic]"
```

```python
from pydantic import BaseModel

class Result(BaseModel):
    title: str

parsed = client.responses.parse(
    model="model",
    input="Return JSON.",
    text_format=Result,
)
```

Manual JSON schema dictionaries are also accepted.

