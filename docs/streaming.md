# Streaming

`stream=True` returns a context manager and iterator.

```python
with client.responses.create(model="model", input="Say hi", stream=True) as stream:
    for event in stream:
        if event.type == "response.output_text.delta":
            print(event.data["delta"], end="")
```

The stream aggregates deltas and exposes `get_final_response()`.

