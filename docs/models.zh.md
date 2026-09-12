# 模型列表

```python
models = client.models.list()
for model in models:
    print(model.id)
```

模型列表来自 OpenAI Codex 的公开模型清单：

```text
https://raw.githubusercontent.com/openai/codex/main/codex-rs/models-manager/models.json
```

结果在内存中缓存五分钟。传入 `force_refresh=True` 可重新获取。当测试需要替换清单，或上游地址发生变化时，可设置 `GPT_CODEX_CLIENT_MODELS_MANIFEST_URL`，也可以在构造客户端时传入 `models_manifest_url`：

```python
client = CodexClient(models_manifest_url="https://example.test/models.json")
```

`Model.raw` 保留原始能力元数据，包括未知字段。能力字段缺失表示未知，不代表支持或不支持；客户端不会根据模型名称推断能力。公开清单不是经过账号授权的模型发现接口，不能保证当前账号具有调用权限。
