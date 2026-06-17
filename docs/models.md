# Models

```python
models = client.models.list()
for model in models:
    print(model.id)
```

The list is cached in memory for five minutes. Pass `force_refresh=True` to
fetch it again.

