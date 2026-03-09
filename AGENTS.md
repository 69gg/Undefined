# Repository Guidelines

## Project Structure & Module Organization
`src/Undefined/` contains the main Python package. Core areas include `ai/`, `cognitive/`, `services/`, `skills/`, and `webui/`. `tests/` holds the pytest suite; add new tests close to the behavior they cover with `test_*.py` names. `apps/undefined-console/` is the Tauri + Vite management client. `code/NagaAgent/` is a Git submodule, so keep upstream syncs and local patches as clearly separated changes. Packaged assets live in `res/`, `img/`, and `config/`; generated outputs like `dist/` and runtime data under `logs/` are not primary edit targets.

## Build, Test, and Development Commands
Use `uv` for the root project:

- `uv sync` installs Python dependencies.
- `uv run playwright install` installs browser runtimes used by screenshot features.
- `uv run Undefined-webui` starts the recommended local management entrypoint.
- `uv run pytest tests/` runs the backend test suite.
- `uv run ruff check .` and `uv run ruff format --check .` enforce Python linting and formatting.
- `uv run mypy .` runs strict type checks.
- `uv build --wheel` validates packaging and resource inclusion.

For the desktop console app, run `cd apps/undefined-console && npm ci && npm run check`. Use `npm run tauri:dev` for local desktop development.

## Coding Style & Naming Conventions
Use 4-space indentation. Python code should be type-annotated and Ruff-formatted; follow `snake_case` for modules and functions, `PascalCase` for classes, and keep modules focused. WebUI JavaScript in `src/Undefined/webui/static/js/` is formatted with Biome using 4-space indents. `code/NagaAgent/frontend/` follows Vue/TypeScript conventions enforced by ESLint.

## Testing Guidelines
Write tests as `tests/test_<feature>.py`. Async tests are supported through `pytest-asyncio`. Add or update tests for behavior changes in APIs, config loading, cognitive memory, and WebUI routes. CI runs the full Python suite plus console checks on pushes and pull requests; no explicit coverage threshold is configured, so use judgment and cover touched paths well.

## Commit & Pull Request Guidelines
Recent history follows Conventional Commits with optional scopes, for example `fix(webui): refine launcher return flow` and `docs(build): document linux no-strip workaround`. Keep subjects imperative and concise. For pull requests, include a short impact summary, linked issues, and the commands you ran. Attach screenshots for WebUI or Tauri UI changes. If you change versioned release files, keep `pyproject.toml` and `src/Undefined/__init__.py` in sync. To mirror local checks, enable repo hooks with `git config core.hooksPath .githooks`.
