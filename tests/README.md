# 测试目录

本目录用于存放测试用例（`pytest` + `pytest-asyncio`）。

运行方式：
```bash
uv run pytest
```

建议在提交前执行：
```bash
uv run ruff format .
uv run ruff check .
uv run mypy src/Undefined
```
