# Repository Guidelines

## Project Structure & Module Organization

- `src/Undefined/`: main Python package (entrypoint: `Undefined.main:run`, also `uv run -m Undefined`).
- `src/Undefined/skills/`: plugin system
  - `skills/tools/<tool_name>/`: atomic tools (e.g., `get_current_time/handler.py`, `config.json`)
  - `skills/toolsets/<category>/<tool_name>/`: grouped tools exposed as `{category}.{tool_name}`
  - `skills/agents/<agent_name>/`: higher-level agents (`intro.md`, `prompt.md`, `handler.py`, `config.json`, optional `mcp.json`)
- `res/`: prompt/templates and prepared messages.
- `config/`: example configs (e.g., `config.toml.example`, `mcp.json.example`).
- `img/`, `logs/`: assets and runtime output (avoid committing generated artifacts).

说明：发行包（wheel）会包含 `res/**` 与 `img/**`。运行时通过 `Undefined.utils.resources` 读取资源文件：优先加载运行目录下的同名路径（便于自定义覆盖），若不存在再回退到安装包自带资源，避免依赖启动目录。

## Build, Test, and Development Commands

This repo uses `uv` for dependency management:

```bash
# Dependencies
uv sync                              # install/sync all dependencies
uv sync --group dev                  # include dev dependencies (mypy, ruff, pytest)

# Running
uv run -m Undefined                  # run the bot locally
uv run playwright install            # required for browser tooling

# Linting & Formatting
uv run ruff check .                  # lint all files
uv run ruff check --fix .            # lint and auto-fix issues
uv run ruff format .                 # format all files
uv run ruff format --check .         # check formatting without changes

# Type Checking
uv run mypy src/Undefined            # strict type-check (configured in pyproject.toml)

# Testing
uv run pytest                        # run all tests
uv run pytest -v                     # verbose output
uv run pytest tests/test_specific.py # run single test file
uv run pytest -k test_function_name  # run tests matching pattern
uv run pytest --cov=src/Undefined    # run tests with coverage
```

## Code Style Guidelines

### Formatting
- Python: 4-space indentation
- Line length: 88 characters (Black-compatible, ruff default)
- Use trailing commas in multi-line structures
- Run `uv run ruff format .` before committing

### Imports
- **Always use absolute imports** (the project enforces this)
- Group imports: stdlib → third-party → local (with blank lines between)
- Sort imports with ruff (enforced by linting)
- Example:
  ```python
  import asyncio
  import logging
  from pathlib import Path
  from typing import Any, Dict, Optional

  import httpx
  from rich.console import Console

  from Undefined.config import get_config
  from Undefined.utils.paths import DATA_DIR
  ```

### Type Hints
- Use type hints for all function signatures (mypy runs in strict mode)
- Use `from __future__ import annotations` for forward references
- Use `Optional[Type]` or `Type | None` for nullable types (Python 3.11+)
- Use `TYPE_CHECKING` guard for imports only used for type hints

### Naming Conventions
- `snake_case`: functions, variables, modules, packages
- `PascalCase`: classes, exceptions
- `UPPER_SNAKE_CASE`: constants, module-level configuration
- `_leading_underscore`: internal/private functions and variables

### Error Handling
- Use specific exceptions over generic `Exception`
- Log exceptions with context using `logger.exception()` in except blocks
- Use `try/except/finally` for resource cleanup
- Prefer early returns over deep nesting

### Logging
- Use module-level logger: `logger = logging.getLogger(__name__)`
- Use appropriate log levels: debug for details, info for milestones, warning for issues, error for failures
- Never log sensitive data (tokens, passwords, API keys)

## Skills Development

Skills should be portable and self-contained:

- Avoid heavy imports from the main app
- Prefer `context` injection for dependencies
- Use `Undefined.context` helpers (e.g., `get_group_id()`)
- Keep handler functions simple and focused
- Always include `config.json` with proper schema

## Cross-Platform Notes

- Avoid platform-specific modules/commands in plugins (e.g., `fcntl`, `find`, `grep`)
- Prefer pure Python implementations
- Use shared helpers under `src/Undefined/utils/` for file operations

## Testing Guidelines

- Framework: `pytest` + `pytest-asyncio`
- Place tests under `tests/` and name files `test_*.py`
- Use `asyncio_mode = auto` (configured in pyproject.toml)
- For new tools/agents, test `handler.py` behavior including:
  - Happy path
  - Error handling
  - Timeout scenarios (where relevant)

## Commit & Pull Request Guidelines

- Follow Conventional Commits: `feat(scope): ...`, `fix(scope): ...`, `refactor(scope): ...`, `docs(...): ...`, `chore(...): ...`, `ci: ...`
- 每次完成变更后顺手 commit，不要等待用户重复提醒
- PRs should include:
  - Clear description of changes
  - Linked issue/PR number if applicable
  - How to test the changes
  - Notes for any `.env`/MCP/config changes
- Never commit secrets: keep `.env` local (copy from `.env.example`) and redact tokens/IDs from logs and screenshots
