# Tool Calls

Use `FunctionTool` for Responses-native tool definitions:

```python
from gpt_codex_client import FunctionTool

tool = FunctionTool(
    name="lookup",
    description="Look up a record.",
    parameters={
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
    },
)
```

Chat compatibility also accepts Chat Completions-style function tools.

