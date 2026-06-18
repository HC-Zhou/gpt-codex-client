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
    model="gpt-5.5",
    input="Return JSON.",
    text_format=Result,
)
```

Manual JSON schema dictionaries are also accepted.
