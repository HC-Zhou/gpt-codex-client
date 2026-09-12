# 发布流程

1. 同步更新 `CHANGELOG.md` 和 `CHANGELOG.zh-CN.md`。
2. 确保 `src/gpt_codex_client/__init__.py` 和 `pyproject.toml` 中的版本号一致。
3. 运行检查：

```bash
uv run ruff format --check
uv run ruff check src tests
uv run mypy src/gpt_codex_client tests --strict
uv run pytest -q
uv build
```

4. 创建 `vX.Y.Z` 标签并推送。

## 双语文档维护

英文源文件使用 `docs/<page>.md`，对应中文使用 `docs/<page>.zh.md`。共享图片放在 `docs/assets/`。站内链接继续写为 `responses.md` 等不带语言后缀的路径，构建时自动解析为当前语言。

英文位于站点根路径，中文位于 `/zh/`；页头语言菜单跳转到当前页面的对应译文。新增页面时同时提供两种语言，并在 `mkdocs.yml` 中补充导航翻译。

发布前使用 `uv run mkdocs build --strict` 验证双语站点。本地预览使用 `uv run mkdocs serve`。
