# Codex 传输协议与真实请求/响应案例

> 此记录是发布前的历史采集快照；源码摘要与 validation.json 描述采集当时的状态，不代表后续 v1.0 源码仍具有相同摘要。

本文针对本仓库 `gpt-codex-client` 的 **ChatGPT OAuth Codex 后端适配**，说明 SDK 参数如何变成请求、如何消费事件、如何续接及解释 usage，并附带一次真实模型调用的脱敏数据。

## 1. 范围、版本与证据

- 采集开始时间：**2026-09-12 22:56:04（Asia/Shanghai）**，即 14:56:04 UTC。
- SDK 源码：本地 `add-codex-session-cache-and-usage` 实现；包版本字段 `0.2.0`。采集时实际 `client_version` 查询参数与 User-Agent 版本仍为 `0.1.0`，这是配置中的独立字段，不能从包版本推导。
- 请求模型和三轮响应的 `model` 字段均为 **`gpt-5.5`**。该字段是服务端返回的模型标识，不是对后端模型内部实现的独立鉴定。
- 实际访问域名：`chatgpt.com`；WebSocket 握手 **101**，SSE 请求 **200**。
- 业务案例是**演示报价**：真实模型推理 + 本地 Decimal 工具运算；价格是明确标记的演示数据，不涉及真实订单、支付或外部查询。
- 本文中“实测”指这一次同步 Responses 案例；Chat 投影、异步、断流恢复和并发清理仍由离线测试覆盖，本次未对这些场景重复调用真实服务。

完整记录：

- [运行清单与源码 SHA-256](artifacts/protocol-case-20260912-run2/manifest.json)
- [按序号排列的完整脱敏轨迹](artifacts/protocol-case-20260912-run2/trace.jsonl)
- [三轮统计](artifacts/protocol-case-20260912-run2/summary.json)
- [第一轮请求](artifacts/protocol-case-20260912-run2/turn-1-request.json) / [响应](artifacts/protocol-case-20260912-run2/turn-1-response.json)
- [第二轮请求](artifacts/protocol-case-20260912-run2/turn-2-request.json) / [响应](artifacts/protocol-case-20260912-run2/turn-2-response.json)
- [第三轮请求](artifacts/protocol-case-20260912-run2/turn-3-request.json) / [响应](artifacts/protocol-case-20260912-run2/turn-3-response.json)

认证 token、账户 ID、账户配额和不透明路由状态已脱敏；加密推理字段若存在，以长度和摘要替代。本次没有返回 reasoning item，不能据此宣称验证了加密推理的真实回放。

这是应用层采集：WebSocket 的 JSON 数据在 send/recv 边界记录，HTTPX 记录请求 body 与已消费的 SSE 字节。**不是 TCP/TLS 抓包**，字节统计不含 TLS、HTTP 头或 WebSocket 帧开销；握手请求只记录 SDK 显式提供的头，不包括库自动生成的 Upgrade/Sec-WebSocket 头。

展示的 JSON 经脱敏和重新排版，不应拿排版后的文本去验证原始字节数。轨迹中的 bytes/sha256 在脱敏前对应用层数据计算；运行清单中的 trace_sha256 则针对最终交付的脱敏 JSONL。

首次采集因记录器将带重复 Set-Cookie 的响应头转换成 dict 而失败，未发出生成帧；[失败清单](artifacts/protocol-case-20260912/manifest.json)单独保留，未混入成功案例的性能数据。

## 2. SDK 层与线上协议的对应关系

```text
Responses.create / parse               Chat.completions.create
        │                                      │
        │                           Chat messages → Responses items
        └──────────────────┬───────────────────┘
                           ▼
                   完整请求快照
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
        HTTP POST + SSE           WebSocket response.create
          完整 input              可用时 ID + 新增 input
             └─────────────┬─────────────┘
                           ▼
              JSON 事件 → ResponseState
                           │
              Response / Usage / Chat 投影
```

`stream=False` 只是 SDK 聚合结果的接口选择：后端请求仍带 `stream:true`，SDK 消费到终态后返回 Response；`stream=True` 则将事件交给调用方。本次三个调用都使用 stream=True 以记录事件。

### 2.1 请求参数映射

| SDK 参数 | 请求体 / 行为 | 本次值或边界 |
| --- | --- | --- |
| model | `model` | gpt-5.5 |
| input | `input` 数组；字符串先转为 user message | 完整历史由调用者提交 |
| instructions | 顶层 `instructions` | 三轮完全相同 |
| tools | 顶层 `tools` | function 工具定义 |
| tool_choice | 顶层 `tool_choice` | auto |
| parallel_tool_calls | 同名布尔字段 | false，未开启并行工具调用 |
| reasoning | 顶层 `reasoning` | 请求仅发送 effort=low |
| text | 顶层 `text` | 本次未指定；响应显示服务端默认 |
| include | 顶层 `include` | preserve_context 合并 encrypted_content 请求 |
| preserve_context | 本地控制，无同名 wire 字段 | true；不保证必然返回 reasoning |
| session_id | 内部索引与会话头 | 无同名 body 字段 |
| prompt_cache_key | 顶层 `prompt_cache_key` | 本次显式等于 session_id |
| transport | 本地选择 SSE/WS | 不发送 transport 字段 |
| previous_response_id | 手动指定时透传；自动增量时内部加入 | 第二轮由 SDK 加入 |
| timeout | I/O 等待配置 | 本次 60 秒，不发送到 body |
| store | SDK 固定写入 false | 三轮返回也为 false |

未指定缓存 key 时从 session_id 派生；长 session 标识使用 SHA-256，显式 key 超过 64 Unicode 字符会拒绝。建议会话 ID 使用 ASCII，以兼容 HTTP 请求头。完整规则见 [Responses 接口](responses.zh.md)。

### 2.2 认证与会话头

实际 WebSocket 地址：

```text
wss://chatgpt.com/backend-api/codex/responses?client_version=0.1.0
```

实际 SDK 提供的握手请求头（脱敏）：

```json
{
  "authorization": "<redacted>",
  "user-agent": "gpt-codex-client/0.1.0",
  "originator": "gpt-codex-client",
  "chatgpt-account-id": "<redacted>",
  "session-id": "protocol-case-d808093affd3443b8ec3d200a5d2fa31",
  "x-client-request-id": "protocol-case-d808093affd3443b8ec3d200a5d2fa31"
}
```
握手成功状态为 101。当前 WS 适配器删除 SSE 的 accept、content-type、openai-beta；本次未发送 OpenAI-Beta 也成功连接，这仅证明此端点在本次运行中接受该请求，不能泛化为所有 Responses 服务都不需要版本头。

SSE 使用同一后端路径的 HTTPS POST，实际请求头如下：

```json
{
  "authorization": "<redacted>",
  "content-type": "application/json",
  "accept": "application/json",
  "user-agent": "gpt-codex-client/0.1.0",
  "openai-beta": "responses=v1",
  "originator": "gpt-codex-client",
  "chatgpt-account-id": "<redacted>",
  "session-id": "protocol-case-d808093affd3443b8ec3d200a5d2fa31",
  "x-client-request-id": "protocol-case-d808093affd3443b8ec3d200a5d2fa31"
}
```
特别注意实际 `accept` 是 application/json，但 body 中 stream=true，响应内容确实是 SSE；不要将文档示例惯用的 `accept: text/event-stream` 冒充本次发送值。采集到的白名单响应头未包含 Content-Type，本次依据实际 event/data 帧识别 SSE。

session-id 标识会话，prompt_cache_key 标识缓存路由意图，previous_response_id 标识要续接的响应，三者职责不同。工具 call_id 则用于把工具结果关联到模型发出的工具调用。

## 3. 真实案例：模型请求工具，本地计算，再回传结果

目标是计算：129.50 × 2 × (1 − 0.1) = **233.10 元**。

```text
应用                 同一条 WS 连接                 Codex
 │  第一轮：完整 user + 工具定义 ─────────────────────▶│
 │◀──────── function_call(calculate_quote, arguments) │
 │                                                    │
 │  本地 Decimal 运算，生成 function_call_output       │
 │                                                    │
 │  第二轮：resp_1 + 仅工具结果 ──────────────────────▶│
 │◀────────────── 中文报价说明，终态 completed         │
 │                                                    │
 │  第三轮：新 HTTPS POST，完整历史 + 追加问题 ────────▶│
 │◀───────────────── SSE：“233.10 元”                 │
```

第三轮是显式指定 SSE 的同一案例延续，**不是 WS 失败后的自动回退**。

### 3.1 第一轮：完整 WebSocket 请求

轨迹 seq=4；以下为完整 JSON payload（仅格式化），应用层 JSON 为 **1,303 字节**：

```json
{
  "type": "response.create",
  "model": "gpt-5.5",
  "input": [
    {
      "role": "user",
      "content": "演示报价：单价129.50元，数量2，折扣率10%。请调用calculate_quote计算折后总额，然后说明计算结果。"
    }
  ],
  "stream": true,
  "store": false,
  "instructions": "You are a quote assistant in a synthetic protocol demonstration. Use calculate_quote exactly once when no tool result exists. After a tool result, answer briefly in Chinese using that result; do not call tools again unless asked to calculate new numbers. Do not invent prices or claim real purchases.",
  "tool_choice": "auto",
  "parallel_tool_calls": false,
  "include": [
    "reasoning.encrypted_content"
  ],
  "prompt_cache_key": "protocol-case-d808093affd3443b8ec3d200a5d2fa31",
  "tools": [
    {
      "type": "function",
      "name": "calculate_quote",
      "description": "Compute a demo quote from the supplied numeric inputs. All prices are demonstration data.",
      "parameters": {
        "type": "object",
        "properties": {
          "unit_price": {
            "type": "number"
          },
          "quantity": {
            "type": "integer"
          },
          "discount_rate": {
            "type": "number"
          }
        },
        "required": [
          "unit_price",
          "quantity",
          "discount_rate"
        ],
        "additionalProperties": false
      },
      "strict": true
    }
  ],
  "reasoning": {
    "effort": "low"
  }
}
```
这里 `type:response.create` 是 WS 消息信封。工具的 strict=true 和 additionalProperties=false 随定义发送；模型只输出调用请求，SDK 不执行工具。

第一轮没有可见回答文本，这不是空响应错误：它成功输出了一次 function_call。完整终态保存在附件，以下抽取其身份、状态、output 和标准 usage，省略的 attribution 可在原记录查看：

```json
{
  "id": "resp_0861e76844c4855e016aa5680981dc87d0bada30cb61ae3463",
  "model": "gpt-5.5",
  "status": "completed",
  "store": false,
  "previous_response_id": null,
  "output": [],
  "usage": {
    "input_tokens": 233,
    "input_tokens_details": {
      "cache_write_tokens": 0,
      "cached_tokens": 0
    },
    "output_tokens": 32,
    "output_tokens_details": {
      "reasoning_tokens": 0
    },
    "total_tokens": 265
  }
}
```
**实际终态 output 是空数组。** 工具调用在此前 seq=56 的 output_item.done 中完成：

```json
{
  "type": "response.output_item.done",
  "item": {
    "id": "fc_0861e76844c4855e016aa5680aeb9487d09c02ec403abfc007",
    "type": "function_call",
    "status": "completed",
    "arguments": "{\"unit_price\":129.5,\"quantity\":2,\"discount_rate\":0.1}",
    "call_id": "call_guVJLZrBpwwdl78P7aWmDL82",
    "name": "calculate_quote"
  },
  "output_index": 0,
  "sequence_number": 23
}
```

SDK 从该事件保留完整 item，再与终态元数据及 usage 合并。不能只读取最后一个事件的 output 来判断有没有工具调用。

三个 ID 不可混用：

- `response.id`：下一轮 previous_response_id 的值。
- `output[].id`（fc_...）：这个协议输出项的 ID，用于事件定位和原始回放。
- `output[].call_id`（call_...）：应用提交 function_call_output 时必须保留的关联键。

arguments 的类型是 **JSON 字符串**。应用验证 name、arguments schema 及预期输入后，才执行本地计算；不能把未结束的 delta 当成完整参数。

### 3.2 实际工具参数流

第一轮共 28 个事件，其中 function_call_arguments.delta 为 19 个。下面直接抽取前 5 个参数片段和最终 done 事件：

```json
[
  {
    "type": "response.function_call_arguments.delta",
    "delta": "{\"",
    "item_id": "fc_0861e76844c4855e016aa5680aeb9487d09c02ec403abfc007",
    "obfuscation": "TetS549JgzIPn4",
    "output_index": 0,
    "sequence_number": 3
  },
  {
    "type": "response.function_call_arguments.delta",
    "delta": "unit",
    "item_id": "fc_0861e76844c4855e016aa5680aeb9487d09c02ec403abfc007",
    "obfuscation": "Rr1Df2Zrq3uI",
    "output_index": 0,
    "sequence_number": 4
  },
  {
    "type": "response.function_call_arguments.delta",
    "delta": "_price",
    "item_id": "fc_0861e76844c4855e016aa5680aeb9487d09c02ec403abfc007",
    "obfuscation": "7ZdWC4pKss",
    "output_index": 0,
    "sequence_number": 5
  },
  {
    "type": "response.function_call_arguments.delta",
    "delta": "\":",
    "item_id": "fc_0861e76844c4855e016aa5680aeb9487d09c02ec403abfc007",
    "obfuscation": "bymmjLObWOGbKO",
    "output_index": 0,
    "sequence_number": 6
  },
  {
    "type": "response.function_call_arguments.delta",
    "delta": "129",
    "item_id": "fc_0861e76844c4855e016aa5680aeb9487d09c02ec403abfc007",
    "obfuscation": "bSNws000twnuY",
    "output_index": 0,
    "sequence_number": 7
  }
]
```

```json
{
  "type": "response.function_call_arguments.done",
  "arguments": "{\"unit_price\":129.5,\"quantity\":2,\"discount_rate\":0.1}",
  "item_id": "fc_0861e76844c4855e016aa5680aeb9487d09c02ec403abfc007",
  "output_index": 0,
  "sequence_number": 22
}
```
delta 是增量文本，不是独立 JSON。应在同一输出项上按顺序拼接；done 携带完整字符串，不能再把它追加一遍。现有 SDK 使用归约器处理这一边界。

### 3.3 本地工具结果

轨迹 seq=61，工具由采集脚本中的 Decimal 运算执行，结果如下。这是本地计算输出，不是模型自行生成的报价依据：

```json
{
  "type": "function_call_output",
  "call_id": "call_guVJLZrBpwwdl78P7aWmDL82",
  "output": "{\"currency\": \"CNY\", \"subtotal\": \"259.00\", \"discount_amount\": \"25.90\", \"total\": \"233.10\", \"demo_data\": true}"
}
```
`function_call_output.output` 同样是字符串；本例里面装 JSON。SDK 调用方此时维护的完整历史为：

```text
input[0]：原用户消息
input[1]：第一轮完整 function_call 输出项
input[2]：本地 function_call_output
```

### 3.4 第二轮：自动增量续接

轨迹 seq=62 记录了 SDK 接收的完整请求，seq=63 记录实际发送数据。第二轮没有再次握手，仍为 connection=1。

下面是实际第二轮请求中的关键字段，其余 tools、instructions、reasoning、include 等仍完整发送且与第一轮一致；完整请求见附件：

```json
{
  "type": "response.create",
  "model": "gpt-5.5",
  "store": false,
  "stream": true,
  "previous_response_id": "resp_0861e76844c4855e016aa5680981dc87d0bada30cb61ae3463",
  "prompt_cache_key": "protocol-case-d808093affd3443b8ec3d200a5d2fa31",
  "input": [
    {
      "type": "function_call_output",
      "call_id": "call_guVJLZrBpwwdl78P7aWmDL82",
      "output": "{\"currency\": \"CNY\", \"subtotal\": \"259.00\", \"discount_amount\": \"25.90\", \"total\": \"233.10\", \"demo_data\": true}"
    }
  ]
}
```
增量规划依据为：

```text
上一轮 input + 上一轮 output
= 原用户消息 + function_call
= 当前完整 input 的前 2 项

因此只发送第 3 项：function_call_output。
```

注意：SDK 没有省略 instructions/tools，也没有发送整份历史的哈希让服务端猜测内容。它只把 input 的匹配前缀换成 previous_response_id。

第二轮实际结果：

```json
{
  "id": "resp_0861e76844c4855e016aa5680c8d8087d0a35f5ad4de996a28",
  "model": "gpt-5.5",
  "status": "completed",
  "store": false,
  "previous_response_id": "resp_0861e76844c4855e016aa5680981dc87d0bada30cb61ae3463",
  "output": [],
  "usage": {
    "input_tokens": 314,
    "input_tokens_details": {
      "cache_write_tokens": 0,
      "cached_tokens": 0
    },
    "output_tokens": 53,
    "output_tokens_details": {
      "reasoning_tokens": 0
    },
    "total_tokens": 367
  }
}
```
第二轮实际的完整消息项在 seq=175，终态帧的 output 同样为空：

```json
{
  "type": "response.output_item.done",
  "item": {
    "id": "msg_0861e76844c4855e016aa5680da65c87d0bc12eb2bb162939a",
    "type": "message",
    "status": "completed",
    "content": [
      {
        "type": "output_text",
        "annotations": [],
        "logprobs": [],
        "text": "演示报价结果如下：\n\n- 小计：259.00 元\n- 折扣金额：25.90 元\n- 折后总额：233.10 元\n\n以上为演示数据，非真实购买价格。"
      }
    ],
    "phase": "final_answer",
    "role": "assistant"
  },
  "output_index": 0,
  "sequence_number": 53
}
```

输出保留 `phase:final_answer`、role、annotations 等字段。应用继续回放时应使用 to_input_items()，不要只取 output_text 重造 assistant message，否则严格前缀匹配可能失败。

第二轮共 58 个事件，其中 output_text.delta 为 47 个；SDK 的 output_text 是这些文本最终的完整表示，不包括加密推理或工具元数据。

### 3.5 第三轮：SSE 全量回放

轨迹 seq=181 的请求为 HTTPS POST，实际 body 为 **2,067 字节**，input 包含 5 项：原用户消息、工具调用、工具结果、第二轮 assistant 回答和追加问题。没有 previous_response_id，也没有顶层 type:response.create。完整 JSON 见[第三轮请求附件](artifacts/protocol-case-20260912-run2/turn-3-request.json)。

实际追加问题是：

> 请根据已有工具结果，只输出折后总额，不重新调用工具。

SSE 使用空行划分事件，原始已消费响应片段是这种结构（以下选取实际终态字段，完整帧见 trace seq=194）：

```text
event: response.completed
data: { ...实际终态 JSON，见下方... }

```

```json
{
  "id": "resp_0861e76844c4855e016aa56811c22887d0a33cb34af47db569",
  "model": "gpt-5.5",
  "status": "completed",
  "store": false,
  "previous_response_id": null,
  "output": [],
  "usage": {
    "input_tokens": 389,
    "input_tokens_details": {
      "cache_write_tokens": 0,
      "cached_tokens": 0
    },
    "output_tokens": 8,
    "output_tokens_details": {
      "reasoning_tokens": 0
    },
    "total_tokens": 397
  }
}
```
第三轮文本实际位于 seq=193 的消息项中：

```json
{
  "type": "response.output_item.done",
  "item": {
    "id": "msg_0861e76844c4855e016aa56812a56087d09680420f49c57864",
    "type": "message",
    "status": "completed",
    "content": [
      {
        "type": "output_text",
        "annotations": [],
        "logprobs": [],
        "text": "233.10 元"
      }
    ],
    "phase": "final_answer",
    "role": "assistant"
  },
  "output_index": 0,
  "sequence_number": 10
}
```

第三轮共 12 个事件，output_text.delta 为 4 个。读取终态后 SDK 即关闭 HTTP 响应，不等待 [DONE] 或 EOF。采集到的已消费 SSE body 为 **9,919 字节**；这不代表服务端原本打算发送的所有尾部字节。

本次 WS 通过 json.dumps 默认 ASCII 转义序列化，HTTPX 的 JSON body 使用不同的紧凑/UTF-8 序列化方式。因此不能直接把第三轮 SSE 的 2,067 字节与假设 WS 全量的 2,492 字节解释为协议本身节省的字节。

## 4. 服务端事件契约

| 事件 | 本次观察 | SDK 行为 |
| --- | --- | --- |
| codex.rate_limits | WS 每轮各 1 次 | 原样透传；交付记录隐去账户配额，不作为 token usage |
| codex.response.metadata | WS 每轮各 1 次 | 原样透传；本次包含 x-models-etag、x-codex-turn-state，后者脱敏 |
| response.created / response.in_progress | 三轮均出现 | 更新 response 元数据，非终态 |
| response.output_item.added | 三轮均出现 | 按输出索引或 item_id 建立输出项 |
| response.function_call_arguments.delta / done | 第一轮 | 累积参数并接受完整 done 值 |
| response.content_part.added / done | 第二、三轮 | 作为合法协议事件透传，原始内容在终态保留 |
| response.output_text.delta / done | 第二、三轮 | 累积文字，避免 done 重复拼接 |
| response.output_item.done | 三轮 | 保留完整工具/消息项和未知字段 |
| responsesapi.websocket_timing | WS 每轮各 1 次 | 透传诊断字段，不能替代 usage 或客户端时间 |
| response.completed | 三轮均出现 | 终态成功；释放资源后交付最后事件 |
| response.incomplete / response.failed / error | 本次未出现 | 按已有终态/异常契约处理；仅离线覆盖 |

### 4.1 原始终态与 SDK 聚合结果必须分开

本次三轮 completed 的原始 response.output 都是 []。工具或消息项已在 output_item.done 返回，终态负责给出 status、usage 等元数据。ResponseState 不会用终态空数组抹掉已累积项。

原始帧与归约结果对应如下：

| 轮次 | output_item.done 序号 | completed 序号 | 原始终态 output | SDK 聚合 output |
| --- | ---: | ---: | --- | --- |
| 1 | 56 | 60 | [] | 1 个 function_call |
| 2 | 175 | 179 | [] | 1 个 assistant message |
| 3 | 193 | 195 | [] | 1 个 assistant message |

附件另提供 [第一轮 SDK 结果](artifacts/protocol-case-20260912-run2/turn-1-sdk-response.json)、[第二轮 SDK 结果](artifacts/protocol-case-20260912-run2/turn-2-sdk-response.json)、[第三轮 SDK 结果](artifacts/protocol-case-20260912-run2/turn-3-sdk-response.json)。它们由所记录事件通过同一版 ResponseState 离线归约得到，文件中明确标注 provenance，不冒充服务端原始 completed 帧；其 output_text 与真实调用时记录的 manifest 一致。

这也是客户端流聚合的实际必要性：即使业务只需要最终答案，也必须完整消费并积累事件。

所有未知但合法 JSON 事件不应被误判为完成。`[DONE]` 本身也不是有效成功终态。协议新增字段保存在 raw/data 中，类型化字段只投影已经明确支持的语义。

本次 WebSocket 首个事件是 codex.rate_limits，**不是首个可见文字 token**。因此下节“首事件耗时”不能称为 TTFT。

## 5. 缓存、字节与 token：本次究竟优化了什么

### 5.1 实测统计

| 轮次 | 传输 | 完整 input 项数 | 实发 input 项数 | 请求 JSON 字节 | 输入 token | 输出 token | 缓存读/写 | 总 token |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| 1 | WebSocket | 1 | 1 | 1,303 | 233 | 32 | 0 / 0 | 265 |
| 2 | 同一 WebSocket | 3 | 1 | 1,335 | 314 | 53 | 0 / 0 | 367 |
| 3 | SSE | 5 | 5 | 2,067 | 389 | 8 | 0 / 0 | 397 |

第二轮若使用同样的 WS JSON 序列化发送完整请求，载荷为 1,780 字节。实发 1,335 字节，差值 445 字节：

```text
(1780 - 1335) / 1780 = 25.00%
```

1,780 是同轮完整请求的本地等价序列化结果，不是另发一次对照请求测量所得。第二轮实发比第一轮大并不矛盾：工具结果与 response ID 本身也占空间。

三轮累计服务端报告输入 936、输出 93、总 token 1,029，缓存读/写均为 0，reasoning_tokens 均为 0。**服务端仍计算了续接上下文的输入 token；省略网络 input 不等于从计量中删除历史。**

### 5.2 时间口径

| 轮次 | SDK 调用到首事件 | SDK 调用到完整结果 |
| --- | ---: | ---: |
| 1 | 1,863.909 ms | 4,242.359 ms |
| 2 | 647.374 ms | 4,430.602 ms |
| 3 | 1,938.511 ms | 2,562.535 ms |

计时使用客户端单调时钟，包含网络、流处理与采集记录开销；首轮还包含握手。各轮输入/输出及工作不同，不构成 SSE 对 WS 的受控性能对比。第二轮总耗时高于第一轮，也不能据此得出增量没有收益。

### 5.3 Usage 映射

| SDK 字段 | 实际响应路径 | 解释 |
| --- | --- | --- |
| input_tokens | usage.input_tokens | 服务端输入总量，不减 cached_tokens |
| output_tokens | usage.output_tokens | 服务端输出总量 |
| cached_tokens | usage.input_tokens_details.cached_tokens | 缓存读取，本次明确为 0 |
| cache_write_tokens | usage.input_tokens_details.cache_write_tokens | 缓存写入，本次明确为 0，不是缺失 |
| reasoning_tokens | usage.output_tokens_details.reasoning_tokens | 本次明确为 0 |
| total_tokens | usage.total_tokens | 服务端总量，不由 SDK 推算 |

若字段缺失则为 None，而不是 0。Usage.raw 深拷贝保留全部原始 usage。此次真实响应还包含 `usage.attribution`，按 items、tools、instructions 分解 token，SDK 没有丢弃它。

例如第二轮 attribution 中：tools=134、instructions=60、原用户项=37、旧 function_call=34、工具结果=47、新消息项输入=2，加和为 314。这是该次返回值的核算，不应假设所有模型都返回同一 attribution schema。

### 5.4 响应中的缓存字段不等于请求配置

第二轮还实际返回了这些字段：

```json
{
  "prompt_cache_retention": "24h",
  "prompt_cache_options": {
    "comparison_response_id": "resp_0861e76844c4855e016aa5680981dc87d0bada30cb61ae3463",
    "mode": "implicit",
    "ttl": "30m"
  },
  "prompt_cache_diagnostics": {
    "type": "unavailable"
  }
}
```
请求中只显式发送 prompt_cache_key，没有发送 prompt_cache_retention 或 prompt_cache_options。服务端返回的 retention=24h 与 options.ttl=30m 同时存在，但 diagnostics=unavailable；SDK 不解释二者优先级，也不据此保证实际保留时长或有缓存命中。

另外，responsesapi.websocket_timing 中第一轮 engine_total_prompt_tokens_total=402，第二轮为 885，后者 num_engine_calls=2、timing_scope=logical_turn；这与当前响应 usage.input_tokens 的 233/314 口径不同。不要把诊断累计数当成当前请求可计量输入，也不要混合求和。

官方资料说明提示词前缀匹配和连接内状态复用是不同机制，可参考 [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) 与 [WebSocket mode](https://developers.openai.com/api/docs/guides/websocket-mode)。这些公开 Responses 文档用于解释概念，不替代 ChatGPT Codex 私有后端的本次实测。这里没有发送额外长提示词来追求命中，也没有对未命中的具体原因作服务端无法证实的断言。

## 6. 错误、恢复与资源释放

以下为当前 SDK 实现与离线规格，本次成功案例没有触发这些错误，不应标记为真实服务验证：

| 情况 | SDK 契约 |
| --- | --- |
| WS 连接失败、生成帧确定未发送 | auto 可回退 SSE；显式 websocket 报错 |
| HTTP 握手业务拒绝 | 暴露 AuthError/APIError，不自动绕过 |
| 发送结果不明、输出途中断流 | StreamError，保留部分结果，不自动重放 |
| 自动增量明确 previous_response_not_found，且无生成输出 | 最多一次新 WS 全量恢复 |
| 手动 previous_response_id | 不进行自动规划，也不保证全量恢复 |
| incomplete | Responses 可返回，默认不可 to_input_items 回放，也不建立续接 |
| 流提前关闭或异步取消 | 关闭连接、清理续接；取消继续传播 |

会话缓存按客户端实例内 session_id 索引，默认 32 个持久条目、空闲 300 秒到期；超 55 分钟的连接在下次复用前更换。同 session busy 或容量全 busy 时，额外请求使用一次性全量连接。没有公开 Session 对象；不处理账户隔离或账户轮换策略。

`client.close_session(id)` / `await client.aclose_session(id)` 清理指定会话；`close()` / `aclose()` 清理所有 SDK 自有 WS，不关闭调用者提供的 httpx 客户端。过期任务与活动流同时被清理。此案例最后明确关闭了 connection=1（seq=196）。

## 7. 如何复现与检查证据

采集脚本位于仓库 `scripts/capture_protocol_case.py`。它仅在显式启动时调用真实服务，读取已有未过期 token，不触发自动登录，也不属于 pytest 默认测试。示例所有金额与业务文本都是演示输入。

```bash
uv sync --extra websocket
uv run python scripts/capture_protocol_case.py   --model gpt-5.5   --output docs/artifacts/protocol-case-local-new
```

输出目录必须不存在，避免覆盖历史证据。再次运行会产生新的真实模型请求；响应文本、ID、usage、时间可能变化。成功案例的首轮 tool call、参数和 Decimal 计算都由脚本校验；工具结果固定依据实际参数计算而不是让模型随意声明。

读取顺序建议：manifest → summary → 第二轮 request/response → trace。trace 中 `sdk.full_request` 是调用方完整请求，`ws.send`/`http.request` 是实际应用层发送载荷，`ws.recv` 是服务端 JSON 帧，`sdk.event` 是 SDK 交付事件，`local.tool_result` 是本地工具执行结果。同一 WS 响应会同时出现 ws.recv 和 sdk.event，统计时不能重复计数。

## 8. 本次验证结论与未验证项

**已实测：** OAuth Codex 地址可达，gpt-5.5 接受该工具 schema；一条 WS 完成两轮；第二轮使用真实 previous_response_id + 单个工具结果成功续接；store=false 可用；SSE 完整历史回放成功；六个 usage 字段实际可读；输出项 phase、调用 ID 与服务端未知字段保留。

**未实测：** 缓存读取命中、加密 reasoning 回放、异步真实传输、Chat 真实投影、并发/过期/异常恢复真实服务路径、其他模型/账户/代理配置、稳定的延迟或费用收益。本次数据不能支持这些更广的结论。
