# Undefined Chat Full Product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `apps/undefined-chat` from the Phase 0 PoC into the complete native-first WebChat client backed by Runtime as the only source of truth.

**Architecture:** Runtime owns conversations, history, jobs, events, attachments, and command metadata. Tauri owns local connection config, API key custody, Runtime HTTP/SSE/upload/download bridges, and platform-specific preview behavior. React owns only UI state, drafts, current selection, event cursors, and rendering of Runtime-returned data.

**Tech Stack:** Python aiohttp Runtime API, pytest/ruff/mypy, Tauri v2 Rust, React 19 + TypeScript + Vitest, existing GitHub Actions release pipeline.

---

## File Structure

- Modify `src/Undefined/api/routes/chat.py`: formal WebChat job contract, per-conversation concurrency, active jobs array, attachment upload/download/preview, structured send normalization, `waiting_input`/`requires_action` reservation.
- Modify `src/Undefined/api/webchat_store.py`: stable `message_id`, references storage, richer attachment metadata, old-history compatibility.
- Modify `src/Undefined/api/app.py`: register new attachment download/preview routes if missing.
- Modify `src/Undefined/api/_openapi.py` and `docs/openapi.md`: document the promoted Runtime contract.
- Add/modify `tests/test_runtime_api_chat_*.py`: red-green coverage for message IDs, structured send, attachments, active jobs, and per-conversation locking.
- Refactor `apps/undefined-chat/src-tauri/src/*.rs`: replace PoC commands with production commands for config, secrets, runtime calls, SSE subscription lifecycle, streaming upload/download, platform info, and HTML preview.
- Refactor `apps/undefined-chat/src/**/*.tsx|ts|css`: split PoC single screen into typed runtime client, store/reducer, conversation list, message timeline, composer, rendering, settings, and i18n modules.
- Modify `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.githooks/pre-commit`, `.githooks/pre-tag`, `scripts/bump_version.py`, `scripts/release_notes.py`, and tests: add Undefined Chat to quality, release, and version synchronization.
- Add/update `docs/undefined-chat.md`, `apps/undefined-chat/README.md`, `README.md`, `docs/app.md`, `docs/build.md`, `docs/webui-guide.md`, `scripts/README.md`.

## Task 1: Runtime Stable History IDs

**Files:**
- Modify: `src/Undefined/api/webchat_store.py`
- Modify: `src/Undefined/api/routes/chat.py`
- Test: `tests/test_runtime_api_chat_history.py`

- [ ] **Step 1: Write failing tests**
  - Add coverage that newly appended WebChat records include stable string `message_id`.
  - Add coverage that old records without `message_id` return deterministic IDs in `GET /api/v1/chat/history`.
  - Add coverage that repeated history reads return the same IDs.

- [ ] **Step 2: Verify red**
  - Run: `uv run pytest tests/test_runtime_api_chat_history.py -q`
  - Expected before implementation: assertions fail because `message_id` is missing.

- [ ] **Step 3: Implement**
  - Generate `message_id` in `WebChatConversationStore.append_message()`.
  - Add a deterministic legacy helper based on conversation id, record timestamp, role, index, and content hash.
  - Include `message_id` in `_history_record_to_item()`.
  - Preserve old JSON files by lazy-normalizing in memory and on next write only.

- [ ] **Step 4: Verify green**
  - Run: `uv run pytest tests/test_runtime_api_chat_history.py -q`

## Task 2: Runtime Per-Conversation Job Concurrency

**Files:**
- Modify: `src/Undefined/api/routes/chat.py`
- Test: `tests/test_runtime_api_chat_jobs.py`

- [ ] **Step 1: Write failing tests**
  - Different conversations can each create a running job.
  - Same conversation returns `409`.
  - Delete and clear only block the target conversation.
  - `GET /api/v1/chat/jobs/active` returns `jobs[]` and keeps compatible `job`.

- [ ] **Step 2: Verify red**
  - Run: `uv run pytest tests/test_runtime_api_chat_jobs.py -q`
  - Expected before implementation: global lock behavior rejects different-conversation job creation and active response lacks `jobs`.

- [ ] **Step 3: Implement**
  - Replace global blocking check in `ChatJobManager.create_job()` with conversation-scoped blocking.
  - Add `get_active_jobs(conversation_id: str | None = None)`.
  - Change `has_running_job()` and `clear_history_when_idle()` to accept a conversation id and only inspect matching jobs.
  - Update conversation list `is_running` using active job set.
  - Update delete and clear handlers to use target conversation lock.

- [ ] **Step 4: Verify green**
  - Run: `uv run pytest tests/test_runtime_api_chat_jobs.py tests/test_runtime_api_chat_history.py -q`

## Task 3: Runtime Native Attachment API

**Files:**
- Modify: `src/Undefined/api/routes/chat.py`
- Modify: `src/Undefined/api/app.py`
- Test: `tests/test_runtime_api_chat_attachments.py`

- [ ] **Step 1: Write failing tests**
  - Upload persists metadata and bytes, returns `discarded: false`, `id`, `name`, `size`, `media_type`, `kind`, and download URLs.
  - `GET /api/v1/chat/attachments/{id}` downloads exact bytes with safe `Content-Disposition`.
  - `GET /api/v1/chat/attachments/{id}/preview` returns image bytes for images and `415` for non-previewable files.
  - Oversize upload returns `413` with `max_upload_size_bytes`.
  - Path traversal style filenames are sanitized.

- [ ] **Step 2: Verify red**
  - Run: `uv run pytest tests/test_runtime_api_chat_attachments.py -q`

- [ ] **Step 3: Implement**
  - Add a small Runtime WebChat attachment store rooted under the existing data path.
  - Stream multipart chunks to a temporary file, enforce Runtime max size while reading, then atomically move into attachment storage.
  - Store metadata JSON separately from bytes.
  - Expose download and preview handlers with strict id validation, safe filename, MIME detection, and no local path disclosure.
  - Keep `GET /api/v1/chat/attachments/capabilities` as the client source for upload limits.

- [ ] **Step 4: Verify green**
  - Run: `uv run pytest tests/test_runtime_api_chat_attachments.py -q`

## Task 4: Runtime Structured Send, References, and Action Reservation

**Files:**
- Modify: `src/Undefined/api/routes/chat.py`
- Modify: `src/Undefined/api/webchat_store.py`
- Test: `tests/test_runtime_api_chat_jobs.py`
- Test: `tests/test_runtime_api_chat_history.py`
- Test: `tests/test_runtime_api_chat_stream.py`

- [ ] **Step 1: Write failing tests**
  - `POST /api/v1/chat/jobs` accepts old `{ "message": "text" }`.
  - `POST /api/v1/chat/jobs` accepts new `{ "message": { "text": "...", "attachment_ids": [], "references": [] } }`.
  - Empty text plus no attachment returns `400`.
  - Unknown conversation returns `404`.
  - Unknown attachment returns `404`; attachment uploaded for another conversation/scope returns `403` when scope is available.
  - History user item includes `references` and normalized attachment metadata.
  - Job snapshot includes `waiting_input: null`.
  - Event stream accepts a reserved `requires_action` event without breaking existing event types.

- [ ] **Step 2: Verify red**
  - Run: `uv run pytest tests/test_runtime_api_chat_jobs.py tests/test_runtime_api_chat_history.py tests/test_runtime_api_chat_stream.py -q`

- [ ] **Step 3: Implement**
  - Add structured payload parser that returns normalized text, attachment ids, references, and display history metadata.
  - Convert references into Runtime-owned history metadata and AI-visible quoted text.
  - Convert attachment ids into AI-visible attachment XML and history attachment metadata.
  - Keep old string message compatibility for WebUI.
  - Add `waiting_input` field to snapshots, defaulting to `None`.
  - Allow sanitized `requires_action` events in buffers and history display where present.

- [ ] **Step 4: Verify green**
  - Run: `uv run pytest tests/test_runtime_api_chat_jobs.py tests/test_runtime_api_chat_history.py tests/test_runtime_api_chat_stream.py tests/test_runtime_api_chat_attachments.py -q`

## Task 5: Tauri Production Runtime Bridge

**Files:**
- Modify: `apps/undefined-chat/src-tauri/src/lib.rs`
- Modify: `apps/undefined-chat/src-tauri/src/config.rs`
- Modify: `apps/undefined-chat/src-tauri/src/runtime_client.rs`
- Modify: `apps/undefined-chat/src-tauri/src/secret.rs`
- Modify: `apps/undefined-chat/src-tauri/src/upload.rs`
- Add: `apps/undefined-chat/src-tauri/src/state.rs`
- Add: `apps/undefined-chat/src-tauri/src/download.rs`
- Add: `apps/undefined-chat/src-tauri/src/platform.rs`
- Test: `apps/undefined-chat/src-tauri/src/poc_tests.rs` or focused Rust unit tests.

- [ ] **Step 1: Write failing tests**
  - Config normalizes Runtime URL and rejects non-HTTP origins.
  - API key commands never return the vault password to React.
  - Runtime request URL builder only targets configured Runtime origin.
  - SSE parser turns chunks into typed events and tracks sequence.
  - Upload still streams from Rust file handle.

- [ ] **Step 2: Verify red**
  - Run: `cd apps/undefined-chat && cargo test --manifest-path src-tauri/Cargo.toml`

- [ ] **Step 3: Implement**
  - Add commands: `get_runtime_config`, `save_runtime_config`, `clear_runtime_config`, `save_api_key`, `load_api_key_status`, `delete_api_key`, `unlock_vault`, `confirm_insecure_storage_fallback`.
  - Add Runtime commands: `runtime_request`, `list_conversations`, `get_history`, `get_active_jobs`, `send_message`, `cancel_job`, `list_commands`, `fetch_job_events_json`.
  - Replace PoC `start_job_event_stream` with subscription id lifecycle: `start_job_event_stream` emits parsed events and returns immediately; `stop_job_event_stream` cancels it.
  - Keep JSON fallback command for platforms or failures where SSE is not stable.
  - Add download helper for attachment save/preview bytes without exposing arbitrary local paths to React.

- [ ] **Step 4: Verify green**
  - Run: `cd apps/undefined-chat && npm run tauri:fmt:check && npm run tauri:check`

## Task 6: React App Architecture and Runtime Store

**Files:**
- Replace: `apps/undefined-chat/src/App.tsx`
- Add: `apps/undefined-chat/src/runtime-client/*`
- Add: `apps/undefined-chat/src/chat-store/*`
- Add: `apps/undefined-chat/src/i18n/*`
- Test: `apps/undefined-chat/src/**/*.test.ts`

- [ ] **Step 1: Write failing tests**
  - Store bootstraps config, health, conversations, active jobs, and current history.
  - Store blocks send only for the selected conversation with an active job.
  - Store handles `connecting`, `connected`, `streaming`, `resuming`, `json_fallback`, `disconnected`.
  - Store applies job events by `seq` without duplicating events after reconnect.
  - i18n defaults to Chinese and exposes English keys.

- [ ] **Step 2: Verify red**
  - Run: `cd apps/undefined-chat && npm run test -- --run`

- [ ] **Step 3: Implement**
  - Add typed Runtime DTOs matching Runtime API.
  - Add reducer/actions for connection, conversations, history pages, active jobs, composer drafts, attachment uploads, references, commands, and settings.
  - Add Tauri event listener glue for SSE chunks/events and JSON fallback polling.
  - Keep local drafts per conversation; do not persist history as source of truth.

- [ ] **Step 4: Verify green**
  - Run: `cd apps/undefined-chat && npm run typecheck && npm run test`

## Task 7: Chat-First UI, Timeline, Composer, and Rendering

**Files:**
- Add: `apps/undefined-chat/src/conversation-list/*`
- Add: `apps/undefined-chat/src/message-timeline/*`
- Add: `apps/undefined-chat/src/message-composer/*`
- Add: `apps/undefined-chat/src/rendering/*`
- Modify: `apps/undefined-chat/src/styles.css`
- Test: `apps/undefined-chat/src/**/*.test.tsx`

- [ ] **Step 1: Write failing tests**
  - Conversation list renders running states for multiple conversations.
  - Timeline renders text, Markdown-ish content, attachments, references, tool/Agent calls, job status, and errors.
  - Timeline uses windowed rendering for large histories.
  - Composer supports text, Enter send, Shift+Enter newline, attachment queue, references, command suggestions, and disabled state for current-conversation running job.
  - HTML preview action calls Tauri preview command.

- [ ] **Step 2: Verify red**
  - Run: `cd apps/undefined-chat && npm run test -- --run`

- [ ] **Step 3: Implement**
  - Visual thesis: quiet native chat workspace, dense but readable, with conversation state visible and the message flow dominant.
  - Content plan: left conversation rail on desktop; chat timeline center; settings/detail drawer only on demand; mobile starts directly in chat with conversation/settings as separate page states.
  - Interaction thesis: restrained drawer transitions, stable auto-scroll, hover/tap affordances for tool details and attachments.
  - Implement responsive layout using CSS media queries, safe-area insets, stable toolbar and composer dimensions.
  - Use accessible buttons, icon-sized controls where existing dependencies allow, and concise Chinese UI labels.
  - Render safe HTML with sanitization strategy and put executable HTML only through isolated Tauri preview.

- [ ] **Step 4: Verify green**
  - Run: `cd apps/undefined-chat && npm run lint && npm run typecheck && npm run test`

## Task 8: CI, Release, Version, Hooks

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `.githooks/pre-commit`
- Modify: `.githooks/pre-tag`
- Modify: `scripts/bump_version.py`
- Modify: `scripts/release_notes.py`
- Test: `tests/test_release_notes_script.py`
- Add: `tests/test_bump_version_script.py`

- [ ] **Step 1: Write failing tests**
  - Release validation fails when Undefined Chat `package.json`, `package-lock.json`, `Cargo.toml`, `tauri.conf.json`, or `Cargo.lock` version differs from `pyproject.toml`.
  - Bump script updates Console and Chat manifests and lock files.

- [ ] **Step 2: Verify red**
  - Run: `uv run pytest tests/test_release_notes_script.py tests/test_bump_version_script.py -q`

- [ ] **Step 3: Implement**
  - Add shared app manifest metadata for `undefined-console` and `undefined-chat`.
  - Add Chat quality job in CI.
  - Release both products with distinct artifact names.
  - Add Chat to hooks and pre-tag validation.
  - Keep version source of truth in `pyproject.toml`.

- [ ] **Step 4: Verify green**
  - Run: `uv run pytest tests/test_release_notes_script.py tests/test_bump_version_script.py -q`

## Task 9: Product Documentation

**Files:**
- Add: `docs/undefined-chat.md`
- Modify: `docs/openapi.md`
- Modify: `docs/app.md`
- Modify: `docs/build.md`
- Modify: `docs/webui-guide.md`
- Modify: `README.md`
- Modify: `apps/undefined-chat/README.md`
- Modify: `scripts/README.md`

- [ ] **Step 1: Update docs**
  - Add “Undefined Chat vs WebUI WebChat” capability table.
  - Document Runtime as source of truth, local-only drafts, SSE-first/JSON fallback, secure storage and Linux fallback, upload limits, HTML preview isolation, and Android lifecycle expectations.
  - Document CI/release/version behavior for Chat.

- [ ] **Step 2: Verify docs references**
  - Run: `rg "Undefined Chat|undefined-chat|WebUI WebChat|bump_version" README.md docs apps/undefined-chat scripts -n`

## Task 10: Final Verification, Review, Commit, Push

**Files:**
- All touched files.

- [ ] **Step 1: Run full verification**
  - Run: `uv run pytest tests/`
  - Run: `uv run ruff check .`
  - Run: `uv run ruff format --check .`
  - Run: `uv run mypy .`
  - Run: `uv build --wheel`
  - Run: `cd apps/undefined-console && npm run check`
  - Run: `cd apps/undefined-chat && npm run check`
  - If `apps/undefined-chat/src-tauri/target` introduces generated Python files, run `cargo clean --manifest-path apps/undefined-chat/src-tauri/Cargo.toml` before root mypy.

- [ ] **Step 2: Request final code review**
  - Dispatch a final reviewer over the diff from the starting SHA to HEAD.
  - Fix Critical and Important findings.

- [ ] **Step 3: Commit and push**
  - Commit with a Conventional Commit subject.
  - Include `Co-authored-by: GPT-5.5 Codex <noreply@openai.com>` unless hooks or repo policy reject it.
  - Push to `origin feature/chat-app`.
