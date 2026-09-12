## Why

当前 Responses 推理走流式传输，绕过已有请求重试；失败事件、提前 EOF 和工具调用转换缺口可能让调用方把部分结果当作正常完成，或无法继续工具循环。为持续适配 Codex 模型，需要先建立同步与异步一致、可离线验证的协议契约。

## What Changes

- 在建连和响应头阶段应用有界重试，区分临时故障与额度耗尽；输出事件后禁止透明重放。
- **BREAKING**：流失败及缺少终止事件的 EOF 明确抛出携带部分结果的异常，不再静默返回普通结果；终止事件到达后立即结束并关闭资源。
- **BREAKING**：Chat 工具调用输入和返回统一为正确的 Chat/Responses 结构，工具参数增量可流式消费，结束原因区分工具调用、长度限制与正常结束。
- 为原生 Responses 提供无损输出回放接口，为 Chat 提供可显式往返的提供商扩展数据；加密推理内容保持不透明。
- 保留回放来源模型信息和模型清单原始能力字段，声明未知能力及兼容范围，不以清单存在推断账号可用性。
- 使用 MockTransport 和可控流覆盖同步、异步、流式、聚合与多轮工具循环，更新迁移说明。

## Capabilities

### New Capabilities
- `codex-stream-lifecycle`: 推理请求重试、终止状态、部分结果和资源生命周期。
- `chat-tool-roundtrip`: Chat 工具调用编码、流式增量、返回格式及结束原因。
- `response-context-replay`: Responses 无损回放、Chat 扩展承载与模型能力信息保留。

### Modified Capabilities
无；当前没有已建立的 OpenSpec 基线规格。

## Impact

涉及 `_client.py`、`_async_client.py`、`_stream.py`、`_async_stream.py`、`_errors.py`、`_converters.py`、`_chat.py`、`_types.py`、Responses 资源、公开导出及对应文档和测试。保留 Python、httpx 和现有 API 外观；不引入 Pi 运行时依赖。WebSocket、后台模型刷新、账号可用性探测及 Agent 工具执行器不属于本变更。
