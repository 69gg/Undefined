from __future__ import annotations

from pathlib import Path


RUNTIME_JS = Path("src/Undefined/webui/static/js/runtime.js")
RUNTIME_CSS = Path("src/Undefined/webui/static/css/components.css")
MAIN_JS = Path("src/Undefined/webui/static/js/main.js")
APP_CSS = Path("src/Undefined/webui/static/css/app.css")
RESPONSIVE_CSS = Path("src/Undefined/webui/static/css/responsive.css")
I18N_JS = Path("src/Undefined/webui/static/js/i18n.js")


def test_webchat_frontend_reuses_job_message_for_final_message() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")

    assert "activeChatMessageId" in source
    assert 'if (event === "message")' in source
    message_branch = source.split('if (event === "message")', 1)[1].split(
        'if (event === "done")', 1
    )[0]

    assert "ensureStreamingMessage(eventJobId)" in message_branch
    assert 'appendChatMessage("bot", content)' not in message_branch


def test_webchat_frontend_handles_tool_lifecycle_and_webchat_hints() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")

    assert 'event === "token_delta"' not in source
    assert 'event === "tool_delta"' not in source
    assert "pendingToolDeltas" not in source
    assert "appendTokenDelta" not in source
    assert 'event === "tool_start"' in source
    assert 'event === "tool_end"' in source
    assert 'event === "agent_start"' in source
    assert 'event === "agent_end"' in source
    assert 'block.uiHint === "webchat_private_send"' in source
    assert 'block.uiHint === "webchat_end"' in source
    assert 'nextUiHint === "webchat_private_send"' in source


def test_webchat_frontend_renders_live_stage_after_ai_label() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    i18n = I18N_JS.read_text(encoding="utf-8")

    assert 'runtime-chat-role-label">AI' in source
    assert "runtime-chat-stage" in source
    assert 'if (event === "stage")' in source
    assert "setChatStage(item, payload || {})" in source
    assert "setChatStage(item, null)" in source
    assert "formatDurationMs" in source
    assert "payload && payload.elapsed_ms" in source
    assert "Date.now() - runtimeState.activeStageStartedAt" not in source
    assert "runtime.chat_stage_waiting_model" in i18n
    assert "runtime.chat_stage_searching_cognitive_memory" in i18n
    assert ".runtime-chat-stage" in css
    assert "runtime-chat-stage-pulse" in css


def test_webchat_frontend_restores_history_tool_blocks_without_stream_state() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")

    assert "function appendHistoryChatItem" in source
    assert "function renderHistoryTimeline" in source
    assert "function reduceToolBlock" in source
    assert 'entry.event === "message"' in source
    assert 'message.classList.add("tool-only")' in source
    assert "appendHistoryChatItem(item, { scroll: false })" in source
    assert "appendHistoryChatItem(items[idx], {" in source

    history_helper = source.split("function appendHistoryChatItem", 1)[1].split(
        "function clearChatMessages", 1
    )[0]
    assert "applyChatEvent(" not in history_helper
    assert "upsertToolBlock(" not in history_helper
    assert "ensureStreamingMessage(" not in history_helper
    assert "data-job-id" not in history_helper


def test_webchat_frontend_renders_chat_as_event_timeline() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    message_branch = source.split('if (event === "message")', 1)[1].split(
        'if (event === "done")', 1
    )[0]
    timeline_helper = source.split("function upsertTimelineToolBlock", 1)[1].split(
        "function upsertToolBlock", 1
    )[0]

    assert 'appendTimelineMessage(item, content, "bot")' in message_branch
    assert 'updateChatMessage(item, content, "bot")' not in message_branch
    assert "timeline.appendChild(node)" in timeline_helper


def test_webchat_frontend_renders_tool_duration() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")

    assert "block.durationMs" in source
    assert "payload.duration_ms" in source
    assert "statusLabel} · ${durationLabel}" in source


def test_webchat_layout_keeps_input_at_bottom_and_log_scrollable() -> None:
    app_css = APP_CSS.read_text(encoding="utf-8")
    responsive_css = RESPONSIVE_CSS.read_text(encoding="utf-8")
    main_js = MAIN_JS.read_text(encoding="utf-8")

    assert ".main-content.chat-layout {" in app_css
    assert "display: flex;" in app_css
    assert "height: 100dvh;" in app_css
    assert "overflow: hidden;" in app_css
    assert "#appContent" in app_css
    assert "grid-template-rows: auto minmax(0, 1fr);" in app_css
    assert "#tab-chat.active" in app_css
    assert "grid-template-rows: auto minmax(0, 1fr);" in app_css

    chat_card_block = app_css.split(
        ".main-content.chat-layout #tab-chat .chat-runtime-card", 1
    )[1].split(".main-content.chat-layout #tab-chat .runtime-chat-log", 1)[0]
    assert "grid-template-rows: auto minmax(0, 1fr) auto;" in chat_card_block
    assert "min-height: 0;" in chat_card_block

    log_block = app_css.split(
        ".main-content.chat-layout #tab-chat .runtime-chat-log", 1
    )[1].split(".main-content.chat-layout #tab-chat .runtime-chat-input", 1)[0]
    assert "overflow-y: auto;" in log_block
    assert "overscroll-behavior: contain;" in log_block

    input_row_block = app_css.split(
        ".main-content.chat-layout #tab-chat .runtime-chat-input-row", 1
    )[1].split(".main-content.chat-layout #tab-chat .runtime-chat-content", 1)[0]
    assert "position: relative;" in input_row_block
    assert "position: sticky;" not in input_row_block
    assert "position: fixed;" not in input_row_block
    assert "var(--bg-main)" not in input_row_block

    assert ".main-content.chat-layout" in responsive_css
    assert "height: 100dvh;" in responsive_css
    assert "function syncMainContentLayout()" in main_js
    assert (
        'appContent.style.display = state.tab === "chat" ? "grid" : "block";' in main_js
    )
