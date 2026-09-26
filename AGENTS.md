# Repository Guidelines

## Project Structure & Module Organization
`src/Undefined/` contains the main runtime package. Core areas include `ai/`, `services/`, `skills/`, `cognitive/`, `memes/`, `knowledge/`, `api/`, `webui/`, `config/`, `mcp/`, and `automations/` (`AutomationService` runtime plus JSON storage); media-facing integrations live in `arxiv/`, `bilibili/`, `github/`, and `attachments/`. `tests/` holds the pytest suite.

> Single source of truth for the module-level directory tree: [docs/development.md](docs/development.md). This file, `CLAUDE.md`, and `ARCHITECTURE.md` only keep overviews — update the tree first when the layout changes. `apps/undefined-console/` is the Tauri + Vite management client and `apps/undefined-chat/` is the native-first Tauri + React 19 chat client (both connect to the same Management/Runtime services), while `code/NagaAgent/` remains a git submodule and should be updated deliberately, with upstream syncs kept separate from repo-local changes. Runtime and generated state primarily lives under `data/`, `logs/`, and `dist/`; the root `knowledge/` directory stores knowledge-base data rather than application code. Prefer editing source files and docs over generated outputs unless the task is explicitly about runtime state.

## Build, Test, and Development Commands
Use `uv` for the root project:

- `uv sync` installs Python dependencies.
- `uv run playwright install` installs browser runtimes used by screenshot and web tooling features.
- `uv run Undefined-webui` starts the recommended Management-first local entrypoint.
- `uv run Undefined` starts the bot directly.
- `uv run pytest tests/` runs the backend test suite.
- `npm ci --prefix tests/frontend` installs the jsdom driver used by `tests/test_webui_runtime_chat_behavior.py`. Without it those cases **skip silently on a local machine** (on CI they fail instead, which is deliberate). Run it once after cloning if you touch WebUI JS.
- `uv run ruff check .` and `uv run ruff format --check .` enforce Python linting and formatting.
- `uv run mypy .` runs strict type checks.
- `uv build --wheel` validates packaging and bundled resources.
- `bash scripts/install_git_hooks.sh` enables the repository-managed git hooks.

For the console app, run `cd apps/undefined-console && npm ci && npm run check`. Use `npm run dev` for the Vite shell and `npm run tauri:dev` for the desktop shell.

For the native chat client, run `cd apps/undefined-chat && npm ci && npm run check` (Biome + TypeScript + Vitest unit/e2e + `cargo fmt --check`/`cargo check`/`cargo test`). Use `npm run tauri:dev` for the desktop shell.

## Coding Style & Naming Conventions
Use 4-space indentation. Python code must be fully type-annotated and pass strict mypy checks. Disk I/O should go through `src/Undefined/utils/io.py` so writes stay async-safe and atomic. Follow `snake_case` for modules and functions, `PascalCase` for classes, and prefer extending existing services/helpers over introducing one-off abstractions. Skills handlers must not import repo-local modules outside `skills/` (only `Undefined.skills.*` and same-directory relative imports are allowed); pass dependencies through the execution context, share helpers via `src/Undefined/skills/shared.py`, and keep `tests/test_skills_import_boundary.py`'s ratchet baseline shrinking. WebUI JavaScript in `src/Undefined/webui/static/js/` and both native apps use Biome 2.5.10; keep the two package pins, lockfiles, and three configuration schemas in sync. Nested app configurations use `extends: []` (explicit no-inherit) plus their own `formatter.indentStyle = "tab"`, so the root WebUI rules never leak into app checks. App changes must satisfy Biome, TypeScript, and Cargo checks.

## Tools & Features

### `group.get_member_info` — brief parameter
The tool supports a `brief` boolean parameter (`default: false`). When `brief: true`, it returns only the current nickname (group card or QQ nickname) in a single line, suitable for quick queries where the AI needs to address a user by their latest name.

### `group.get_avatar` — fetch user avatar
`group.get_avatar` accepts `user_id` (required) and optional `size` (40, 100, 140, 640, default 100). It downloads the QQ avatar and registers it as an attachment, returning an `<attachment uid="..."/>` tag that can be embedded in messages.

### OneBot local file transport
`[onebot].file_send_mode` selects `local` (default for compatibility, including older configs without this field or an environment override), `url`, or `stream`; URL and Stream require explicit selection. `file_send_host` defaults to `127.0.0.1` and is used only for URL delivery. Both hot reload per logical delivery snapshot. Keep local source paths in business tools, attachment registration and history; `OneBotClient` prepares a separate wire request, including nested forward media. URL mode uses the running Runtime port and per-file 16-minute tokens/copies; Stream requires the NapCat extension, uses 64 KiB chunks and a separate completion request with SHA-256 verification. Stream/URL preparation plus send/fallback share 8 minutes excluding the Stream queue. Preparation errors must not mark delivery or trigger file-segment fallback; uncertain delivery must not be retried. Never log chunk data/tokens, re-interpret completed NapCat paths on the Bot, or call global `clean_stream_temp_file`. The upstream merge and existing attachment registration may still buffer whole files. See [deployment](docs/deployment.md) and [configuration](docs/configuration.md).

### Unified attachment tag
Use `<attachment uid="..."/>` for both images and files. The legacy `<pic uid="..."/>` tag is still supported for backward compatibility but `attachment` is the recommended unified syntax. The system distinguishes image vs file based on the UID prefix (`pic_`/`file_`).
Remote attachments are cached only up to `[attachments].remote_download_max_size_mb`; larger items, or all remote items when the value is `0`, are registered as URL references with `source_ref` instead of downloaded file content.

### Auto processing pipelines
Automatic extraction pipelines live under `src/Undefined/skills/pipelines/<name>/` and use `config.json + handler.py`. Slash commands have higher priority; when a command is dispatched, automatic pipelines and AI auto-reply are skipped. Command inputs and command outputs should be recorded in message history so later AI turns can see the result. For non-command messages, all pipelines detect in parallel and all matches process in parallel before AI auto-reply. Outputs should go through `MessageSender`, which writes history and automatically registers local CQ media or uploaded files as session attachment UIDs.

### Same-sender short-window message batching
Consecutive messages from the same sender within `[message_batcher].window_seconds` are merged into a single AI invocation, so the AI sees the whole batch as `<message>` blocks and decides per-intent (independent request vs. correction/interruption). Pokes always bypass; an at-bot message arriving while a buffer already exists is processed individually so it is not blocked; a first at-bot message that opens the buffer routes the eventual batch through the mention lane. History writes remain unchanged. Configure under `[message_batcher]` (`enabled`, `window_seconds`, `strategy`, `max_window_seconds`, `max_messages_per_batch`, `group_enabled`, `private_enabled`, `pre_send_seconds`, `allow_cancel_after_send`); details in [docs/message-batching.md](docs/message-batching.md). Optional speculative pre-fire (`0 < pre_send_seconds < window_seconds`) dispatches the current batch to the LLM early once the user has been silent for `pre_send_seconds`; new messages can cancel the in-flight call as long as it has not yet sent any reply.

### User identification in prompts
The system prompt now includes a rule: **recognize and address users by their QQ ID (`sender_id`)** because nicknames can change. When needing to address a user, use the latest nickname obtained via `group.get_member_info(brief=true)`. `end.observations` must be substantive facts worth future retrieval (prefer empty over noise); user-centered observations should always include the QQ ID, e.g., “QQ号12345678（昵称张三）做了某事”.

### Reply relevance and member activity semantics
Both main prompt variants and `res/IMPORTANT/each.md` guide replies to add useful information without repeating shared background. Keep exceptions for requested explanations, recaps, complete steps, corrections, and natural social replies; never infer a user's knowledge solely from their identity or terminology.
`group_analysis.member_activity` distinguishes recency (`member_list`), retrieved window message counts (`history`), and weighted indicators (`hybrid`, default). History-mode timestamps must come from messages inside the selected window. History aggregation uses `try_parse_message_time` and skips invalid timestamps before counting or ranking; `parse_message_time` retains its current-time fallback for existing display callers. Missing/zero `last_sent_time` means unknown, not proof of inactivity or never speaking; last-message time does not indicate current online status. See [the toolset documentation](src/Undefined/skills/toolsets/group_analysis/README.md) for reporting limits.

## Testing Guidelines
Write tests as `tests/test_<feature>.py`. Async tests use `pytest-asyncio`. Add or update coverage for behavior changes in APIs, config loading/hot reload, cognitive memory, meme or knowledge flows, and WebUI/runtime routes. If you touch `apps/undefined-console/` or `src/Undefined/webui/static/js/`, run `npm run check` in `apps/undefined-console/` in addition to the Python checks; if you touch `apps/undefined-chat/`, run `npm run check` in `apps/undefined-chat/` (it bundles Vitest unit/e2e suites, so cover changed behavior there). No fixed coverage threshold is configured, so cover touched paths well.

## Commit & Pull Request Guidelines
Recent history follows Conventional Commits with optional scopes, for example `fix(webui): refine launcher return flow` and `feat(commands): add /version (/v) slash command`. Keep commit subjects imperative and concise. Keep `code/NagaAgent/` syncs separate from local feature work when possible. If you are bumping release versions, prefer `uv run python scripts/bump_version.py <version>` so `pyproject.toml`, `src/Undefined/__init__.py`, and the `package.json` + Tauri config of both `apps/undefined-console/` and `apps/undefined-chat/` stay in sync. For pull requests, include a short impact summary, linked issues, and the commands you ran; attach screenshots for WebUI or Tauri UI changes.
