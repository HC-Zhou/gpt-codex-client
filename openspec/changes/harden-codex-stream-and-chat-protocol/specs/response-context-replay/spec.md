## ADDED Requirements

### Requirement: Explicit native Responses replay
Response SHALL 提供 to_input_items()，为 completed 输出返回保持顺序和未知字段的深拷贝，涵盖消息、推理、工具项及其关联 ID。incomplete 或失败结果 MUST NOT 默认作为成功历史回放。

#### Scenario: Native tool roundtrip with reasoning
- **WHEN** 成功响应包含 encrypted_content、消息 phase 和 function_call，调用方将 to_input_items() 与工具结果追加到输入
- **THEN** 回放项保留全部原始协议字段及顺序，修改返回列表不改变原响应

#### Scenario: Incomplete replay rejected
- **WHEN** 对 incomplete 响应调用 to_input_items()
- **THEN** 明确拒绝默认回放，调用方仍能检查原始 output 并自行处理

### Requirement: Opt-in reasoning context preservation
同步与异步 Responses 和 Chat SHALL 支持默认关闭的 preserve_context；启用时 SHALL 将 reasoning.encrypted_content 合并进 include 且不丢失已有 include。加密内容 MUST NOT 出现在展示文本或默认错误消息中。

#### Scenario: Merge includes safely
- **WHEN** 调用方启用 preserve_context 并指定已有 include
- **THEN** 请求同时保留原 include 与 reasoning.encrypted_content，不产生重复项

#### Scenario: Opaque reasoning remains opaque
- **WHEN** 响应包含推理摘要及 encrypted_content
- **THEN** 加密数据仅保存在原始/扩展数据中，不成为 Chat content 或 Response.output_text

### Requirement: Versioned Chat provider context
启用 preserve_context 时 Chat SHALL 在非流式 ChatMessage.provider_data 和流式最终 ChatDelta.provider_data 承载 version=1、provider=codex、model、output_items。ChatMessage.to_dict() SHALL 保留扩展字段。回放 SHALL 使用扩展作为该 assistant 的权威输出并校验公开消息投影一致，不重复生成输出项。

#### Scenario: Serialized Chat context roundtrip
- **WHEN** 调用方保存带 provider_data 的 assistant 消息，加入工具结果后向同一模型再次发送
- **THEN** 回放原始推理及工具项一次且保持关联 ID；流式汇总和非流式消息均支持此契约

#### Scenario: Edited or foreign context
- **WHEN** 扩展版本未知、目标模型或 provider 不同，或公开文本/工具信息与封套不一致
- **THEN** 发送前明确拒绝并说明原因，不静默丢弃推理项；编辑场景提示移除扩展后作为普通 Chat 历史发送

### Requirement: Preserve capability provenance without inventing support
模型数据 SHALL 保留 Model.raw 中来源清单的原始能力及未知字段；文档 SHALL 声明缺失能力为未知，模型清单不保证账号可用性。回放扩展 SHALL 保留来源模型身份，不根据模型名称推断跨模型兼容。

#### Scenario: Unrecognized model metadata
- **WHEN** 模型清单增加未知能力字段或缺失已有能力字段
- **THEN** 新字段在 raw 中保留，缺失字段不被自动解释为支持或不支持，客户端仍允许显式模型 ID
