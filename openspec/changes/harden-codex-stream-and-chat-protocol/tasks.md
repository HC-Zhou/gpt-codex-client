## 1. 建立离线协议回归夹具

- [x] 1.1 使用 httpx.MockTransport 与同步/异步可控字节流建立夹具，支持分片、异常、终态后保持连接及关闭计数；禁止真实 OAuth/Codex 请求。
- [x] 1.2 为三个 capability 的场景建立测试矩阵，覆盖同步/异步、流式/聚合，修正现有接受错误 Chat 工具结构的测试预期。

## 2. 统一响应状态与资源生命周期

- [x] 2.1 扩展 StreamError 的 kind、code、partial_response、raw_event，并定义 get_final_response 在未完成及失败状态的契约。
- [x] 2.2 实现共享事件归约器，按输出项累积文本、工具参数、原始项和 id/model；验证 delta 与完整 output 合并不重复。
- [x] 2.3 处理 error、response.failed、cancelled、response.done、incomplete、无效 JSON 和无终态 EOF；验证未知合法事件透传及 [DONE] 不能伪造完成。
- [x] 2.4 接入同步与异步流，终态到达即关闭响应；验证保持连接、提前退出、异常、异步取消、幂等关闭及外部 HTTP 客户端所有权。

## 3. 修复实际推理路径重试

- [x] 3.1 提取重试分类及延迟策略，支持临时状态码、额度耗尽排除、三种重试头格式及 max_retry_delay 默认 60 秒和参数校验。
- [x] 3.2 在同步/异步流打开路径使用可重建上下文的请求工厂；关闭失败响应后再等待，验证 max_retries=0 和预算耗尽。
- [x] 3.3 验证建连失败、响应头前超时、429/503 后成功在流式和聚合调用均生效；响应体消费后失败不重发并保留部分结果。

## 4. 完成 Chat 工具调用双向转换

- [x] 4.1 将 assistant tool_calls 转为独立 function_call，将工具结果转换为无 role 的 function_call_output，保留 strict 并校验必要字段。
- [x] 4.2 将 Responses 工具结果映射为 Chat id/type/function 结构，arguments 保持字符串，不能投影的工具类型明确报错。
- [x] 4.3 实现共享 Chat 流投影，维护工具 index、名称、ID 和参数增量，覆盖交错调用、done 去重、终态补发及冲突检测。
- [x] 4.4 统一流式/聚合结束原因：tool_calls、stop、length、content_filter；未知 incomplete 抛出含原因的错误。
- [x] 4.5 用两轮 MockTransport 验证 assistant 工具响应经序列化、追加工具结果后发出的下一轮请求结构和 ID 一致。

## 5. 保留与回放提供商上下文

- [x] 5.1 实现 Response.to_input_items() 深拷贝契约，保留未知字段、推理项、phase 与关联 ID，并拒绝 incomplete 默认回放。
- [x] 5.2 为同步/异步 Responses 和 Chat 入口增加 preserve_context，必要的 include 透传及公开类型/导出保持一致；验证合并去重与默认关闭。
- [x] 5.3 实现版本化 provider_data、ChatMessage.to_dict() 和最终 ChatDelta 扩展，确保流式/聚合均可收集并持久化完整回放上下文。
- [x] 5.4 实现封套权威回放与公开字段一致性校验，覆盖跨模型/provider、未知版本、用户编辑、重复输出防护以及加密内容不进入展示文本和默认错误消息。
- [x] 5.5 验证 Model.raw 保留新增能力字段且缺失能力不被推断；验证原生 Responses 和 Chat 同模型推理加工具的完整两轮回放。

## 6. 文档、迁移与验收

- [x] 6.1 更新 streaming/errors 文档，说明重试阶段、等待上限、部分结果、终态、取消和提前退出的资源管理。
- [x] 6.2 更新 chat-compatibility/tool-calls/responses/models 文档，提供工具闭环、to_input_items、provider_data 持久化示例及支持边界。
- [x] 6.3 更新 README 与 CHANGELOG，明确异常与工具结构的破坏性变化、迁移方式和离线验证边界，不宣称真实端点已验证。
- [x] 6.4 运行 uv run ruff format --check、uv run ruff check src tests、uv run mypy src/gpt_codex_client tests --strict、uv run pytest -q 和 uv build，修复失败并记录结果；不自动发布。

## 验收记录

2026-09-12：ruff format --check（23 files）、ruff check、mypy --strict（23 source files）全部通过；pytest 135 passed；uv build 成功生成 sdist 与 wheel。新增测试均使用 MockTransport 和可控流，无真实 OAuth/Codex 调用。未发布、未创建 Git 提交。
