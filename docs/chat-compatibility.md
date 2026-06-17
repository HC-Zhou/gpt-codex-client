# Chat Compatibility

The chat layer accepts Chat Completions-style messages and function tools and
converts them into a Responses request.

```python
completion = client.chat.completions.create(
    model="model",
    messages=[
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "Hello"},
    ],
)
print(completion.choices[0].message.content)
```

System and developer messages are folded into `instructions`.

