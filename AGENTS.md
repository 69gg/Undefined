# Repository Guidelines

## Project Structure & Module Organization
Primary code lives in `src/Undefined/`. Keep changes in the matching domain package: `ai/` for model orchestration, `cognitive/` for memory pipelines, `services/` for runtime services, `skills/` for tools/agents/commands, `webui/` for the management UI, and `utils/` for shared helpers. Tests live in `tests/`. Packaged assets and defaults live in `res/`, `img/`, and `config/`. Scripts are in `scripts/`; docs are in `docs/`.

## Build, Test, and Development Commands
- `uv sync --group dev -p 3.12`: install the project with contributor tooling.
- `uv run playwright install`: install the browser runtime used by rendering and web-driven features.
- `cp config.toml.example config.toml`: create a local config before running the app.
- `uv run Undefined`: start the bot process directly.
- `uv run Undefined-webui`: start the WebUI manager. Do not run this alongside `Undefined`.
- `uv run ruff format .`: apply formatting.
- `uv run ruff check .`: run lint checks.
- `uv run mypy .`: run strict type checking.
- `uv run pytest tests/`: run the full test suite.
- `uv build --wheel`: build the distribution and verify packaged resources.

## Coding Style & Naming Conventions
Use 4-space indentation, Python type hints, and `async`/`await` for I/O paths. Let Ruff drive formatting instead of hand-formatting around it. Use `snake_case` for modules, functions, and variables; `PascalCase` for classes; `UPPER_SNAKE_CASE` for constants. Keep modules narrow in scope, and place new Skills content under the correct subtree such as `skills/tools/`, `skills/toolsets/`, or `skills/agents/`.

## Testing Guidelines
The project uses `pytest` with `pytest-asyncio` (`asyncio_mode = auto`). Name files `tests/test_*.py` and test functions `test_*`. Prefer focused runs while iterating, for example `uv run pytest tests/test_parse_command.py -q`, then finish with the full suite. Add regression coverage for behavior changes in handlers, config loading, Skills discovery, and WebUI routes.

## Commit & Pull Request Guidelines
Follow the commit style already used in history: `feat: ...`, `fix(scope): ...`, `chore(version): ...`. Keep subjects short and imperative. PRs should include a clear summary, linked issue when applicable, the commands you ran (`ruff`, `mypy`, `pytest`), and screenshots for WebUI changes. If you modify `res/`, `img/`, or `config.toml.example`, note that wheel packaging was checked with `uv build --wheel`.

## Security & Configuration Tips
Treat `config.toml` as runtime state and avoid committing secrets. Prefer `config.toml.example` for documented defaults. Outputs under `data/` and `logs/` should stay out of feature commits unless the change explicitly targets fixtures or diagnostics.
