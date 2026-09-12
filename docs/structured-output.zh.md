# 结构化输出

安装可选的 Pydantic 依赖：

```bash
uv add "gpt-codex-client[pydantic]"
```

使用 Pydantic 模型描述预期结构：

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

也支持直接传入 JSON Schema 字典。
