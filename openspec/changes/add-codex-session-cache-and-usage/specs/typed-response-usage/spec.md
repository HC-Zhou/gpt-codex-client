## ADDED Requirements

### Requirement: Typed server usage projection
SDK SHALL 公开 Usage，提供 int | None 字段 input_tokens、output_tokens、cached_tokens、cache_write_tokens、reasoning_tokens、total_tokens。顶层计数 SHALL 映射同名服务端字段；缓存计数 SHALL 来自 input_tokens_details，推理计数 SHALL 来自 output_tokens_details.reasoning_tokens。input_tokens MUST NOT 扣除缓存，total_tokens MUST NOT 自行推算。

#### Scenario: Preserve totals
- **WHEN** 服务端报告 input_tokens=100、cached_tokens=80、cache_write_tokens=10
- **THEN** 类型化结果保留 100、80、10，不将 input_tokens 改为 10

### Requirement: Preserve unknown and raw usage
缺失或 null 字段 SHALL 为 None，明确零 SHALL 为 0；畸形值 SHALL 不强制转换为合法计数。Usage.raw SHALL 独立保留原始 usage 的未知字段，Response.raw SHALL 继续保留完整响应。

#### Scenario: Partial or malformed counters
- **WHEN** cache_write_tokens 缺失、cached_tokens 为 0，或某计数为字符串/负数/布尔值
- **THEN** 缺失和畸形计数为 None，合法零仍为 0，原值保留于 raw

### Requirement: Consistent usage access
Response.usage、ChatCompletion.usage 和终态 ChatCompletionChunk.usage SHALL 暴露相同语义；没有 usage 对象时 SHALL 为 None，非终态 Chat chunk SHALL 为 None。同步/异步和 SSE/WS SHALL 一致，ParsedResponse SHALL 通过 response.usage 访问，不重复定义计量。

#### Scenario: Terminal usage across APIs
- **WHEN** 同一终态 payload 经同步/异步、流式/聚合及 Chat 投影
- **THEN** 六字段值一致，流最终 Response 和终态 Chat chunk 可读取 usage，中间 Chat chunk 不伪造计数
