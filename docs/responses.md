# Responses

```python
from gpt_codex_client import CodexClient, FunctionTool, Reasoning

response = CodexClient().responses.create(
    model="gpt-5.5",
    input="Find the answer.",
    tools=[FunctionTool(name="lookup", parameters={"type": "object"})],
    reasoning=Reasoning(effort="medium"),
)
```

Use `client.models.list()` to discover model slugs available to your account.
