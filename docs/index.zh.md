# 快速开始

`gpt-codex-client` 提供带类型标注的 Python 客户端，接口风格与 OpenAI SDK 相似：

```python
from gpt_codex_client import CodexClient

client = CodexClient()
response = client.responses.create(
    model="gpt-5.5",
    input="Write a compact project summary.",
)
print(response.output_text)
```

本项目对接 ChatGPT/Codex 的 OAuth 后端，不使用 `api.openai.com` 的标准 API Key 认证方式。
