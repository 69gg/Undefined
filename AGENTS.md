# Repository Guidelines

## Project Structure & Module Organization
`src/Undefined/` contains the main runtime package. Core areas include `ai/`, `services/`, `skills/`, `cognitive/`, `memes/`, `knowledge/`, `api/`, `webui/`, `config/`, and `mcp/`; media-facing integrations live in `arxiv/`, `bilibili/`, `github/`, and `attachments.py`. `tests/` holds the pytest suite. `apps/undefined-console/` is the primary Tauri + Vite management client, while `code/NagaAgent/` remains a git submodule and should be updated deliberately, with upstream syncs kept separate from repo-local changes. Runtime and generated state primarily lives under `data/`, `logs/`, and `dist/`; the root `knowledge/` directory stores knowledge-base data rather than application code. Prefer editing source files and docs over generated outputs unless the task is explicitly about runtime state.

## Build, Test, and Development Commands
Use `uv` for the root project:

- `uv sync` installs Python dependencies.
- `uv run playwright install` installs browser runtimes used by screenshot and web tooling features.
- `uv run Undefined-webui` starts the recommended Management-first local entrypoint.
- `uv run Undefined` starts the bot directly.
- `uv run pytest tests/` runs the backend test suite.
- `uv run ruff check .` and `uv run ruff format --check .` enforce Python linting and formatting.
- `uv run mypy .` runs strict type checks.
- `uv build --wheel` validates packaging and bundled resources.
- `bash scripts/install_git_hooks.sh` enables the repository-managed git hooks.

For the console app, run `cd apps/undefined-console && npm ci && npm run check`. Use `npm run dev` for the Vite shell and `npm run tauri:dev` for the desktop shell.

## Coding Style & Naming Conventions
Use 4-space indentation. Python code must be fully type-annotated and pass strict mypy checks. Disk I/O should go through `src/Undefined/utils/io.py` so writes stay async-safe and atomic. Follow `snake_case` for modules and functions, `PascalCase` for classes, and prefer extending existing services/helpers over introducing one-off abstractions. Skills handlers must not import repo-local modules outside `skills/`; pass dependencies through the execution context instead. WebUI JavaScript in `src/Undefined/webui/static/js/` is formatted with Biome, and `apps/undefined-console/` changes must satisfy Biome, TypeScript, and Cargo checks.

## Tools & Features

### `group.get_member_info` — brief parameter
The tool supports a `brief` boolean parameter (`default: false`). When `brief: true`, it returns only the current nickname (group card or QQ nickname) in a single line, suitable for quick queries where the AI needs to address a user by their latest name.

### `group.get_avatar` — fetch user avatar
`group.get_avatar` accepts `user_id` (required) and optional `size` (40, 100, 140, 640, default 100). It downloads the QQ avatar and registers it as an attachment, returning an `<attachment uid="..."/>` tag that can be embedded in messages.

### Unified attachment tag
Use `<attachment uid="..."/>` for both images and files. The legacy `<pic uid="..."/>` tag is still supported for backward compatibility but `attachment` is the recommended unified syntax. The system distinguishes image vs file based on the UID prefix (`pic_`/`file_`).
Remote attachments are cached only up to `[attachments].remote_download_max_size_mb`; larger items, or all remote items when the value is `0`, are registered as URL references with `source_ref` instead of downloaded file content.

### Auto processing pipelines
Automatic extraction pipelines live under `src/Undefined/skills/auto_pipeline/pipelines/<name>/` and use `config.json + handler.py`. Slash commands have higher priority; when a command is dispatched, automatic pipelines and AI auto-reply are skipped. Command inputs and command outputs should be recorded in message history so later AI turns can see the result. For non-command messages, all pipelines detect in parallel and all matches process in parallel before AI auto-reply. Outputs should go through `MessageSender`, which writes history and automatically registers local CQ media or uploaded files as session attachment UIDs.

### User identification in prompts
The system prompt now includes a rule: **recognize and address users by their QQ ID (`sender_id`)** because nicknames can change. When needing to address a user, use the latest nickname obtained via `group.get_member_info(brief=true)`. Observations recorded in cognitive memory should always include the QQ ID, e.g., “QQ号12345678（昵称张三）做了某事”.

## Testing Guidelines
Write tests as `tests/test_<feature>.py`. Async tests use `pytest-asyncio`. Add or update coverage for behavior changes in APIs, config loading/hot reload, cognitive memory, meme or knowledge flows, and WebUI/runtime routes. If you touch `apps/undefined-console/` or `src/Undefined/webui/static/js/`, run `npm run check` in `apps/undefined-console/` in addition to the Python checks. No fixed coverage threshold is configured, so cover touched paths well.

## Commit & Pull Request Guidelines
Recent history follows Conventional Commits with optional scopes, for example `fix(webui): refine launcher return flow` and `feat(commands): add /version (/v) slash command`. Keep commit subjects imperative and concise. Keep `code/NagaAgent/` syncs separate from local feature work when possible. If you are bumping release versions, prefer `uv run python scripts/bump_version.py <version>` so `pyproject.toml`, `src/Undefined/__init__.py`, `apps/undefined-console/package.json`, and the Tauri config stay in sync. For pull requests, include a short impact summary, linked issues, and the commands you ran; attach screenshots for WebUI or Tauri UI changes.
