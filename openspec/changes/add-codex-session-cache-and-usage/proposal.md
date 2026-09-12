## Why

当前 SDK 缺少显式提示词缓存参数和类型化 usage，多轮 Agent 调用也无法复用 WebSocket 上一轮状态以减少历史传输。已有无损回放及共享响应归约器为这些优化提供了基础，可在保持调用方管理完整历史的前提下增加可选加速。

## What Changes

- 同步/异步 Responses create、parse 和 Chat create 增加 session_id、prompt_cache_key 与 transport 参数；缓存 key 未指定时使用 session_id。
- 增加可选 WebSocket 与严格前缀匹配的自动增量发送；默认仍为 SSE，保留 store=false。
- 使用客户端内部会话缓存，不增加公开 Session 对象；支持按 session 清理、空闲过期、数量上限和客户端关闭清理。同 session 并发额外请求使用一次性全量连接。
- 对明确的续接失效提供有限全量恢复，对执行结果不明的断流不自动重放。
- 公开类型化 usage 的 input_tokens、output_tokens、cached_tokens、cache_write_tokens、reasoning_tokens、total_tokens，缺失值保留 None，保留原始数据及服务端 token 语义。
- 增加离线协议、资源生命周期与 usage 测试及中英文用法文档。不开展账户隔离设计，不实现自动历史管理、工具执行、压缩或计费估算。

## Capabilities

### New Capabilities
- `codex-cache-parameters`: 各 SDK 入口一致的会话、缓存标识与传输配置。
- `codex-session-transport`: 内部连接缓存、严格增量、并发与资源清理、失败恢复。
- `typed-response-usage`: Responses 与 Chat 同步/异步、流式/聚合的类型化 usage 和原始数据保留。

### Modified Capabilities

无。仓库尚无 openspec/specs 主规格；既有 harden-codex-stream-and-chat-protocol 变更中的回放、错误和流生命周期契约继续作为兼容约束。

## Impact

影响请求转换器、Responses/Chat 资源、同步/异步客户端、流封装、公开类型与导出，以及测试、文档和依赖配置。新增可选 WebSocket 依赖及客户端内部状态；调用者提供的 httpx 客户端所有权保持不变。默认 SSE 与现有手动 previous_response_id 行为保持兼容；不调用真实 OAuth/Codex 端点，不自动发布。
