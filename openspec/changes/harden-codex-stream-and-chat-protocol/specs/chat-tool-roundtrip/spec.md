## ADDED Requirements

### Requirement: Encode Chat tool history as Responses items
转换器 SHALL 将 assistant tool_calls 转为独立 function_call 项，将工具结果转为无 role 的 function_call_output，保留 call_id、name、arguments 和函数工具 strict 声明。必要 ID、名称及参数类型无效时 SHALL 在发送前明确报错。

#### Scenario: Multi-turn tool history
- **WHEN** 历史包含 assistant 文本、两个工具调用及其工具结果
- **THEN** 发出的 input 依序包含文本消息、两个 function_call 及对应 function_call_output，工具项无嵌套 Chat tool_calls 或 role=tool

### Requirement: Return Chat-shaped tool calls
非流式 Chat SHALL 返回 id、type=function、function.name、function.arguments 结构，arguments 保持字符串，id 使用 call_id。不能表示为 Chat function 的输出工具类型 SHALL 明确报不支持，不静默丢弃。

#### Scenario: Tool response can be replayed
- **WHEN** 将一次 Chat 返回的 assistant 消息序列化并附加工具结果作为下一轮输入
- **THEN** 下一轮编码保持工具名称、参数和关联 ID，并满足 Responses 工具输入契约

#### Scenario: Unsupported custom tool
- **WHEN** Chat 收到不能映射为函数调用的 custom_tool_call
- **THEN** 明确暴露不支持错误，原生 Responses 仍保留该原始输出项

### Requirement: Stream tool call deltas without duplication
Chat 流 SHALL 为每个工具调用分配稳定 index，输出 ID、名称及参数增量，并支持多个工具交错。完成事件 MUST NOT 重复发出已交付参数；终态独有信息 SHALL 补发，无法一致合并的数据 SHALL 报协议错误。

#### Scenario: Interleaved arguments
- **WHEN** 两个工具的参数 delta 交错到达，随后各自发送完整 done 数据
- **THEN** 调用方按 index 拼接后得到两个准确参数字符串，每个字符仅交付一次

#### Scenario: Only terminal tool output exists
- **WHEN** 未收到工具 delta 但 completed.output 包含完整函数调用
- **THEN** 流在结束 chunk 前交付完整工具调用内容

### Requirement: Accurate Chat finish reasons
Chat SHALL 将 completed 且含工具调用映射为 tool_calls，普通 completed 映射为 stop；incomplete 的 max_output_tokens 映射为 length，content_filter 映射为 content_filter，其他 incomplete 原因 SHALL 明确报错并保留原因。流式与聚合结果 SHALL 一致。

#### Scenario: Tool call completion
- **WHEN** completed 输出包含函数调用
- **THEN** 非流式 choice 和流式最终 chunk 的 finish_reason 均为 tool_calls

#### Scenario: Output token limit
- **WHEN** incomplete_details.reason 为 max_output_tokens
- **THEN** finish_reason 为 length，已生成内容可消费，不返回 stop

#### Scenario: Unknown incomplete reason
- **WHEN** incomplete 的原因无法投影为已支持 Chat 结束原因
- **THEN** 抛出带原始原因和部分响应的错误
