# Repository Guidelines

## Project Structure & Module Organization
Core Python code lives in `src/Undefined/`, organized by domain: `ai/`, `services/`, `cognitive/`, `skills/`, `webui/`, and `utils/`.  
Tests are in `tests/` (pytest auto-discovers from this directory).  
Runtime/config assets live in `res/`, `img/`, and `config/`.  
Operational scripts are in `scripts/` (for example, `scripts/reembed_cognitive.py`).  
Documentation is in `docs/`, and CI/release workflows are under `.github/workflows/`.

## Build, Test, and Development Commands
- `uv sync --group dev -p 3.12`: install project + development dependencies.
- `uv run playwright install`: install browser runtime used by rendering/web features.
- `uv run Undefined` or `uv run Undefined-webui`: run bot or WebUI (choose one, do not run both).
- `uv run ruff format .`: auto-format code.
- `uv run ruff check .`: lint checks.
- `uv run mypy .`: strict type checking (project is configured with `mypy` strict mode).
- `uv run pytest tests/`: run full test suite.
- `uv build --wheel`: build distributable wheel (CI also validates packaged resources).

## Coding Style & Naming Conventions
Use 4-space indentation, type annotations, and `async`/`await` for I/O paths when applicable.  
Follow Ruff formatting output; do not hand-tune style against formatter/linter.  
Use `snake_case` for modules/functions/variables, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants.  
Keep modules focused by capability (for example, add chat command logic under `skills/commands/`).

## Testing Guidelines
Frameworks: `pytest`, `pytest-asyncio` (`asyncio_mode = auto`).  
Name tests as `test_*.py` and test functions as `test_*`.  
Prefer targeted runs during development, e.g. `uv run pytest tests/test_parse_command.py -q`.  
Before opening a PR, run format, lint, type check, and full tests locally.  
No fixed coverage gate is enforced, but add tests for behavior changes and regressions.

## Commit & Pull Request Guidelines
Use Conventional Commit style seen in history: `feat: ...`, `fix(scope): ...`, `chore(version): ...`, `refactor: ...`.  
Release tooling groups commits by `feat`/`fix`, so use these prefixes accurately.  
PRs should include: concise summary, linked issue (if any), test evidence (commands/results), and screenshots for WebUI changes.  
Ensure CI passes (`ruff`, `mypy`, `pytest`, build checks) before requesting review.
