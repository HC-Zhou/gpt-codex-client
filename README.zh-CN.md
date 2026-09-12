<p align="center">
  <img src="docs/assets/gpt-codex-client-v1.png" width="132" alt="gpt-codex-client 图标">
</p>

<h1 align="center">gpt-codex-client</h1>

<p align="center">
  <strong>面向 ChatGPT/Codex OAuth 工作流的 OpenAI SDK 风格 Python 客户端。</strong>
</p>

<p align="center">
  <a href="README.md">English</a> · 简体中文 ·
  <a href="https://pypi.org/project/gpt-codex-client/">PyPI 软件包</a> ·
  <a href="https://hc-zhou.github.io/gpt-codex-client/">文档</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/gpt-codex-client/"><img alt="PyPI" src="https://img.shields.io/pypi/v/gpt-codex-client?color=2563eb"></a>
  <a href="https://pypi.org/project/gpt-codex-client/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/gpt-codex-client?color=0891b2"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/HC-Zhou/gpt-codex-client?color=16a34a"></a>
  <a href="https://github.com/HC-Zhou/gpt-codex-client/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/HC-Zhou/gpt-codex-client/actions/workflows/ci.yml/badge.svg"></a>
</p>

`gpt-codex-client` 是一个 OpenAI SDK 风格的 Python 客户端，用于
ChatGPT/Codex OAuth 登录支持的工作流。它不是面向 `api.openai.com` 的
API Key 客户端；它读取和写入兼容 `~/.codex/auth.json` 的本地 token 缓存，
并要求账号具备对应 ChatGPT/Codex 后端访问权限。

## 安装

```bash
uv add gpt-codex-client
```

## 快速开始

```python
from gpt_codex_client import CodexClient

with CodexClient(no_browser=True) as client:
    response = client.responses.create(
        model="gpt-5.5",
        input="Write a short Python function that reverses a string.",
    )
    print(response.output_text)
```

## 亮点

- 提供 Responses 风格的同步和异步客户端，并支持流式输出。
- 提供 Chat Completions 兼容层，便于迁移已有 messages/tool calls 代码。
- 支持 OAuth PKCE 登录、refresh token 和 `~/.codex/auth.json` token 缓存。
- 从 OpenAI Codex 公开模型注册表读取模型列表。
- 可选支持 Pydantic 结构化输出解析。

## 获取模型列表

`client.models.list()` 会读取 OpenAI Codex 仓库中的公开模型注册表，
而不是调用 ChatGPT/Codex 后端的 `/models` 接口。

```python
from gpt_codex_client import CodexClient

with CodexClient() as client:
    models = client.models.list()
    for model in models:
        print(model.id)
```

模型注册表来源：

```text
https://raw.githubusercontent.com/openai/codex/main/codex-rs/models-manager/models.json
```

如果需要使用其他兼容的注册表，可以设置
`GPT_CODEX_CLIENT_MODELS_MANIFEST_URL`，或在构造客户端时传入
`models_manifest_url=`。

## 认证

客户端会在首次请求时懒加载认证。默认读取并写入 `~/.codex/auth.json`，
保存权限为 `0600`。

```python
from gpt_codex_client import login

login(no_browser=True)
```

默认 OAuth client id 与官方 Codex 客户端使用的 ChatGPT/Codex 登录流程一致。
如果你有自己的已注册 client id，可以设置 `GPT_CODEX_CLIENT_OAUTH_CLIENT_ID`，
或在构造 `CodexClient` 时传入 `auth_client_id=`。

自动化场景可以传入 `login_handler`，它会收到授权 URL，并返回最终 redirect URL：

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

流式调用会返回 context manager 和 iterator：

```python
with CodexClient() as client:
    with client.responses.create(model="gpt-5.5", input="Say hi", stream=True) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                print(event.data.get("delta"), end="")
```

## 结构化输出

使用 Pydantic 模型时安装可选 extra：

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

## Chat 兼容层

Chat 兼容层会把 Chat Completions 风格的 messages 和 function tools
转换为 Responses 请求：

```python
completion = CodexClient().chat.completions.create(
    model="gpt-5.5",
    messages=[{"role": "user", "content": "Hello"}],
)
print(completion.choices[0].message.content)
```

## 开发

```bash
uv sync --all-extras --dev
uv run pytest -q
```

## 协议可靠性更新（0.2.0）

流式和聚合推理请求均支持建连阶段重试；流失败通过 StreamError 保留部分结果，
缺少终止事件的 EOF 会明确报错。Chat 工具调用采用 id/type/function 结构，
支持参数增量与准确的结束原因。可选 preserve_context 保留同模型回放所需的不透明上下文。
迁移细节见[流式接口](docs/streaming.md)、[Chat 兼容](docs/chat-compatibility.md)和
[原生回放](docs/responses.md)。验证使用离线 MockTransport，没有调用真实 OAuth/Codex 端点。

## 会话缓存与 usage

Responses、Chat 的同步/异步调用支持 `session_id`、`prompt_cache_key` 和
`transport="sse" | "websocket" | "auto"`。默认仍为 SSE；使用 WebSocket 前安装
`pip install 'gpt-codex-client[websocket]'`。每次传完整历史，并保持稳定 session_id，
由 SDK 自动判断是否发送增量。

usage 存在时可直接读取 `response.usage.input_tokens`、`cached_tokens`、
`cache_write_tokens`、`output_tokens`、`reasoning_tokens`、`total_tokens`。
缺失值为 None，输入总量不扣减缓存 token。

客户端内部维护有上限的连接缓存，不新增公开 Session 对象。使用
`close_session(id)` / `await aclose_session(id)` 或关闭客户端清理自有 WebSocket。
详见[Responses 文档](docs/responses.zh.md#缓存标识与可选-websocket)，包括并发、恢复、
过期、可选依赖与代理限制。当前不处理账户隔离，不保证缓存命中或费用收益。自动化回归使用离线模拟，下方协议文档另行记录了一次同步 WebSocket/SSE 真实案例。

真实请求、工具回传、增量续接与 usage 数据分析见[完整协议文档](docs/protocol.zh.md)。

## GPT 推理强度

```python
response = client.responses.create(
    model="gpt-5.5",
    input="分析这个设计的取舍。",
    model_reasoning_effort="high",
)
```

`model_reasoning_effort` 映射为线上 `reasoning.effort`，不会作为顶层协议字段发送。
同步/异步 Responses 的 `create`、`parse`、流式调用及 `chat.completions.create` 均支持。
已有 `reasoning={"effort": "high", "summary": "auto"}` 和 Chat 的
`reasoning_effort="high"` 保持兼容。同值重复指定可用，冲突值会在联网前抛出
`ValueError`；其他 reasoning 选项保留，不修改调用方输入。

省略时使用后端默认值。SDK 透传非空字符串，不按模型名称过滤，也不硬编码模型能力表；
具体支持的档位由模型和后端决定。[Codex 官方配置文档](https://developers.openai.com/codex/config-reference/)
列出 `minimal`、`low`、`medium`、`high` 和依模型而定的 `xhigh`。
SDK 不会自动读取本地 Codex TOML 中的 `model_reasoning_effort`。
