# Responses 接口

```python
from gpt_codex_client import CodexClient, FunctionTool, Reasoning

response = CodexClient().responses.create(
    model="gpt-5.5",
    input="Find the answer.",
    tools=[FunctionTool(name="lookup", parameters={"type": "object"})],
    reasoning=Reasoning(effort="medium"),
)
```

使用 `client.models.list()` 发现公开清单中的模型名称。清单中存在某个模型不代表当前账号有权调用。

## 原生输出回放

```python
history = [{"role": "user", "content": "Look up record 42"}]
response = client.responses.create(
    model="model", input=history, tools=[FunctionTool(name="lookup")],
    preserve_context=True,
)
history.extend(response.to_input_items())
for item in response.output:
    if item.get("type") == "function_call":
        # Validate and execute in your application; this is example output.
        history.append({"type": "function_call_output", "call_id": item["call_id"],
                        "output": "record 42: example result"})
next_response = client.responses.create(model="model", input=history)
```

`to_input_items()` 按原始顺序返回已完成输出的深拷贝，保留推理项、加密内容、消息阶段、ID 和未知字段。修改副本不会影响原响应。未完成响应不能通过此辅助方法回放；请检查 `output` 和 `raw` 后显式决定如何继续。

保存历史时应记录来源模型。原生输入回放的模型兼容性由调用方负责，Chat 的版本化封套会自行校验模型。

`preserve_context=True` 将 `reasoning.encrypted_content` 合并进 `include`，不移除现有值。该选项默认关闭，在两个客户端的 `create` 和 `parse` 中均可使用。加密上下文保持不透明，不进入 `output_text`。原生输出保留 Chat 不支持的工具类型。

这些契约已通过离线 MockTransport 测试；测试不证明真实 Codex 回放或账号可用性。

## 缓存标识与可选 WebSocket

同步/异步 `responses.create`、`responses.parse`、`chat.completions.create` 一致支持：

| 参数 | 默认值 | 行为 |
| --- | --- | --- |
| `session_id` | `None` | 稳定的对话标识；在 WebSocket 下用于内部连接和续接状态复用 |
| `prompt_cache_key` | `None` | 显式缓存标识；未指定时使用 session_id 派生值 |
| `transport` | `"sse"` | 支持 `sse`、`websocket`、`auto` |

显式 key 必须非空白且不超过 64 个 Unicode 字符。session_id 必须非空白；超过 64 字符时，线上标识为 UTF-8 SHA-256 十六进制摘要，内部索引仍用完整 ID。为兼容 HTTP 头，请使用 ASCII session_id。`session-id`、`x-client-request-id` 使用 session 标识，不随显式 cache key 改变，并以大小写不敏感方式覆盖自定义同名头。没有 session 就不自动添加会话头；只有 cache key 不建立持久会话。两者都未指定时不生成标识。`None` 表示使用会话默认，不表示关闭服务端缓存，也不承诺缓存保留时长或命中。

```bash
pip install 'gpt-codex-client[websocket]'
```

```python
from gpt_codex_client import CodexClient

history = [{"role": "user", "content": "解释这个函数。"}]
with CodexClient(session_cache_max_size=32, session_cache_idle_timeout=300) as client:
    response = client.responses.create(
        model="your-model", input=history,
        session_id="conversation-42", prompt_cache_key="project-context",
        transport="websocket", preserve_context=True,
    )
    history.extend(response.to_input_items())
    history.append({"role": "user", "content": "再总结一下。"})
    followup = client.responses.create(
        model="your-model", input=history,
        session_id="conversation-42", prompt_cache_key="project-context",
        transport="websocket", preserve_context=True,
    )
    if followup.usage is not None:
        print(followup.usage.input_tokens, followup.usage.cached_tokens)
    client.close_session("conversation-42")
```

每次始终传完整历史。SDK 仅在旧 input + 完整 output 是当前 input 的严格前缀，且其他请求字段一致时，发送 previous_response_id 和新增 items；否则发送全量。SDK 不自动追加、编辑历史或执行工具。Chat 应通过 `message.to_dict()` 保留 `provider_data`，流式应用应保存终态 delta 的 `provider_data`。缺失这些数据可能阻止增量发送。`preserve_context` 仍默认关闭。

显式传入 previous_response_id 时，绕过自动增量与缓存更新，WebSocket 使用一次性连接；SDK 不保证能为该手动 ID 恢复完整历史。所有传输保持 store=False。

显式 websocket 暴露连接失败。auto 仅在确认生成帧未提交时回退 SSE，例如未安装可选依赖或连接失败；HTTP 握手拒绝直接暴露。发送结果不明或输出途中断流不自动重放。自动增量收到 previous_response_not_found 且无任何生成输出时，最多新建一次 WebSocket 并发送完整上下文恢复。

### 资源生命周期

缓存由客户端内部按 session_id 管理，不提供公开 Session 对象。默认最多 32 个持久条目、空闲 300 秒过期；容量为非负整数，0 禁用持久缓存；空闲时间必须有限且大于零。缓存满时淘汰空闲 LRU；全部忙碌或同 session 正在使用时，额外请求采用一次性全量连接，不覆盖原状态。一次性连接不计入持久缓存上限，整体并发由调用方控制。连接年龄达到 55 分钟后在下次复用前更换。

`close_session(id)` / `await aclose_session(id)` 清理该 session 的空闲及活动连接（包括一次性连接），活动流会被中止。未知 session 和重复清理无害。`close()` / `await aclose()` 清理全部 SDK 自有 WebSocket 与过期任务，不关闭调用者传入的 httpx 客户端。异步客户端应在同一个事件循环中使用。流提前关闭、失败或取消会丢弃续接；completed 释放连接供复用，incomplete 可以返回但不会建立续接状态。

可选依赖为 `websockets>=15,<16`。握手及接收等待使用请求 timeout，关闭握手上限为 5 秒。WebSocket 独立于 httpx，代理选择遵循 websockets 的环境/系统配置（SOCKS 还需其可选依赖），不会继承自定义 httpx transport、代理或 TLS 设置。依赖这些设置时继续使用 sse。端点变化使旧 WS 失效；本功能不处理账户隔离及轮换策略。

## 类型化 usage

`Response.usage`、`ChatCompletion.usage`、终态 `ChatCompletionChunk.usage` 暴露公开 `Usage`；ParsedResponse 通过 `response.usage` 访问。中间 Chat chunk 的 usage 为 None。

| 字段 | 服务端来源 |
| --- | --- |
| `input_tokens` | `usage.input_tokens`，包含缓存输入 |
| `output_tokens` | `usage.output_tokens` |
| `cached_tokens` | `usage.input_tokens_details.cached_tokens` |
| `cache_write_tokens` | `usage.input_tokens_details.cache_write_tokens` |
| `reasoning_tokens` | `usage.output_tokens_details.reasoning_tokens` |
| `total_tokens` | `usage.total_tokens` |

六个字段均为 int 或 None：缺失、null 或畸形计数保留 None，合法零保留 0。服务端完全未返回 usage 时，`.usage` 为 None。输入不扣减缓存 token，总 token 不自行推算；`Usage.raw` 深拷贝保留未知字段，`Response.raw` 继续保留原始响应。不估算费用，也不根据连接复用或增量传输推断提示词缓存命中。自动化回归使用离线模拟；另见[同步 WebSocket/SSE 真实协议案例](protocol.md)，该案例未证明提示词缓存命中或延迟收益。

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
