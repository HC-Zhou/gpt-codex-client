# Models

```python
models = client.models.list()
for model in models:
    print(model.id)
```

The list is read from the OpenAI Codex model registry:

```text
https://raw.githubusercontent.com/openai/codex/main/codex-rs/models-manager/models.json
```

The result is cached in memory for five minutes. Pass `force_refresh=True` to
fetch it again. Set `GPT_CODEX_CLIENT_MODELS_MANIFEST_URL` to point at another
compatible registry during tests or if the upstream location changes. You can
also pass `models_manifest_url=` when constructing a client:

```python
client = CodexClient(models_manifest_url="https://example.test/models.json")
```

`Model.raw` retains original capability metadata, including unknown fields. A
missing capability means unknown, not supported or unsupported. The client does
not infer capabilities from the model name. This public registry is not an
account-authorized model discovery endpoint and does not guarantee access.
