# Repository Guidelines

## Project Structure & Module Organization

- `src/Undefined/`: main Python package (entrypoint: `Undefined.main:run`, also `uv run -m Undefined`).
- `src/Undefined/skills/`: plugin system
  - `skills/tools/<tool_name>/`: atomic tools (e.g., `get_current_time/handler.py`, `config.json`)
  - `skills/toolsets/<category>/<tool_name>/`: grouped tools exposed as `{category}.{tool_name}`
  - `skills/agents/<agent_name>/`: higher-level agents (`intro.md`, `prompt.md`, `handler.py`, `config.json`, optional `mcp.json`)
- `res/`: prompt/templates and prepared messages.
- `config/`: example configs (e.g., `config/mcp.json.example`).
- `img/`, `logs/`: assets and runtime output (avoid committing generated artifacts).

## Build, Test, and Development Commands

This repo uses `uv` for dependency management:

```bash
uv sync                       # install/sync dependencies
uv run playwright install      # required for browser tooling (web-related skills)
uv run -m Undefined            # run the bot locally
uv run ruff check .            # lint
uv run ruff format .           # format
uv run mypy src/Undefined      # type-check (strict)
```

## Coding Style & Naming Conventions

- Python: 4-space indentation, type hints encouraged (mypy runs in strict mode).
- Prefer absolute imports (the project has refactors enforcing this).
- Naming: `snake_case` for functions/vars, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Skills should be portable: avoid heavy imports from the main app; prefer `context` injection and `Undefined.context` helpers (e.g., `get_group_id()`).

## Testing Guidelines

- Frameworks: `pytest` + `pytest-asyncio`; place tests under `tests/` and name files `test_*.py`.
- For new tools/agents, test `handler.py` behavior (happy path + error/timeout handling where relevant).

## Commit & Pull Request Guidelines

- Follow Conventional Commits as used in history: `feat(scope): ...`, `fix(scope): ...`, `refactor(scope): ...`, `docs(...): ...`, `chore(...): ...`, `ci: ...`.
- PRs should include: clear description, linked issue/PR number if applicable, how to test, and notes for any `.env`/MCP/config changes.
- Never commit secrets: keep `.env` local (copy from `.env.example`) and redact tokens/IDs from logs and screenshots.

