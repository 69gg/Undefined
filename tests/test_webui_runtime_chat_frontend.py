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
    assert "payload && payload.result_preview" in source
    assert 'nextUiHint === "webchat_end"' not in source


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
    assert "function normalizeToolCallNode" in source
    assert "function normalizeHistoryTimelineNode" in source
    assert 'entry.event === "message"' in source
    assert "item.webchat.calls" in source
    assert "item.webchat.timeline" in source
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
    assert "appendNestedTimelineMessage(" in message_branch
    assert 'updateChatMessage(item, content, "bot")' not in message_branch
    assert "timeline.appendChild(node)" in timeline_helper
    assert "parent_webchat_call_id" in timeline_helper
    assert "parent.children" in timeline_helper
    assert (
        'appendToolTimelineEntry(parent, { type: "call", call: block })'
        in timeline_helper
    )
    assert "topLevelToolKey(blocks, parentKey)" in timeline_helper
    assert "runtime-tool-children" in RUNTIME_CSS.read_text(encoding="utf-8")


def test_webchat_frontend_prefers_backend_history_timeline() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    history_timeline_branch = source.split("if (timelineItems.length)", 1)[1].split(
        "if (calls.length)", 1
    )[0]

    assert 'entry.type === "message"' in history_timeline_branch
    assert 'entry.type !== "call"' in history_timeline_branch
    assert "renderToolBlock(entry.call)" in history_timeline_branch
    assert "reduceToolBlock(" not in history_timeline_branch


def test_webchat_frontend_renders_nested_tool_timeline() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    css = RUNTIME_CSS.read_text(encoding="utf-8")

    assert "function renderToolTimelineItem" in source
    assert "function appendNestedTimelineMessage" in source
    assert "function appendToolTimelineEntry" in source
    assert "block.timeline" in source
    assert "renderToolTimelineItem" in source
    assert "runtime-tool-message" in source
    nested_message_helper = source.split("function appendNestedTimelineMessage", 1)[
        1
    ].split("function upsertToolBlock", 1)[0]
    assert "payload.parent_webchat_call_id" in nested_message_helper
    assert 'type: "message"' in nested_message_helper
    assert "redrawToolTimelineNode(item, blocks, parentKey)" in nested_message_helper
    assert "runtime-tool-reveal" in css
    assert ".runtime-tool-block::before" in css
    assert ".runtime-tool-block summary::before" in css


def test_webchat_tool_summary_uses_compact_single_line_order() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    render_helper = source.split("function renderToolBlock", 1)[1].split(
        "function renderToolTimelineItem", 1
    )[0]
    summary_css = css.split(".runtime-tool-block summary {", 1)[1].split(
        ".runtime-tool-block summary::-webkit-details-marker", 1
    )[0]

    assert "runtime-tool-name" in render_helper
    assert "runtime-tool-status" in render_helper
    assert "runtime-tool-kind" in render_helper
    assert (
        render_helper.index("runtime-tool-name")
        < render_helper.index("runtime-tool-status")
        < render_helper.index("runtime-tool-kind")
    )
    assert "grid-template-columns: auto minmax(0, 1fr) auto auto;" in summary_css
    assert "min-height: 34px;" in summary_css
    assert "padding: 4px 10px 4px 13px;" in summary_css
    assert "line-height: 1.2;" in summary_css
    name_css = css.split(".runtime-tool-block summary .runtime-tool-name", 1)[1].split(
        ".runtime-tool-block summary .runtime-tool-status", 1
    )[0]
    assert "font-weight: 650;" in name_css


def test_webchat_tool_blocks_auto_collapse_after_minimum_visible_time() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    assert "TOOL_AUTO_COLLAPSE_MIN_VISIBLE_MS = 2000" in source
    assert "runtimeState.toolCollapseTimers" in source
    assert "function scheduleToolAutoCollapse" in source
    assert 'block.autoOpen ? " open" : ""' in source
    assert "autoOpen: isStart ? true : !!previous.autoOpen" in source
    assert "localStartedAtMs: isStart" in source
    assert "finishedAtMs: isEnd" in source
    collapse_helper = source.split("function scheduleToolAutoCollapse", 1)[1].split(
        "function upsertTimelineToolBlock", 1
    )[0]
    assert "const durationMs = Number(block.durationMs)" in collapse_helper
    assert "TOOL_AUTO_COLLAPSE_MIN_VISIBLE_MS - elapsedMs" in collapse_helper
    assert "latest.autoOpen = false" in collapse_helper
    assert "redrawToolTimelineNode(item, blocks, timerKey)" in collapse_helper
    assert "setTimeout(collapse, delayMs)" in collapse_helper
    clear_helper = source.split("function clearToolCollapseTimers", 1)[1].split(
        "function finishStreamingMessage", 1
    )[0]
    assert "clearTimeout(timer)" in clear_helper


def test_webchat_auto_scroll_toggle_controls_stream_scroll() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    template = Path("src/Undefined/webui/templates/index.html").read_text(
        encoding="utf-8"
    )

    assert "runtimeChatAutoScroll" in template
    assert "runtime.chat_auto_scroll" in template
    assert "CHAT_AUTO_SCROLL_STORAGE_KEY" in source
    assert "readChatAutoScrollPreference()" in source
    assert "setChatAutoScroll(autoScrollToggle.checked)" in source
    assert "if (!runtimeState.chatAutoScroll) return;" in source
    assert "forceScrollChatToBottom()" in source


def test_webchat_frontend_renders_tool_duration() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")

    assert "block.durationMs" in source
    assert "payload.duration_ms" in source
    assert "statusLabel} · ${durationLabel}" in source


def test_webchat_tool_previews_render_structured_input_output() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    i18n = I18N_JS.read_text(encoding="utf-8")

    assert "function formatToolPreview" in source
    assert "JSON.parse(text)" in source
    assert "function renderStructuredToolValue" in source
    assert "function renderToolPreviewSection" in source
    assert '"runtime.tool_input"' in source
    assert '"runtime.tool_output"' in source
    assert "runtime-tool-structured-row" in source
    assert "runtime-tool-key" in source
    assert "runtime-tool-value" in source
    assert "renderChatContent(preview.text, !!options.markdown)" in source

    assert ".runtime-tool-preview" in css
    assert ".runtime-tool-preview-label" in css
    assert ".runtime-tool-preview-body.is-structured" in css
    assert ".runtime-tool-key" in css
    assert ".runtime-tool-value.string" in css
    assert ".runtime-tool-value.number" in css
    assert ".runtime-tool-value.boolean" in css
    assert "runtime.tool_input" in i18n
    assert "runtime.tool_output" in i18n


def test_webchat_tool_error_status_uses_error_color() -> None:
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    error_block = css.split(
        ".runtime-tool-block.error summary .runtime-tool-status", 1
    )[1].split(".runtime-tool-preview", 1)[0]

    assert "color: var(--error);" in error_block
    assert ".runtime-tool-block.cancelled summary .runtime-tool-status" in error_block
    assert "var(--danger)" not in error_block


def test_webchat_send_scrolls_to_bottom_after_layout_updates() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    helper = source.split("function scrollChatToBottomSoon", 1)[1].split(
        "function updateChatMessage", 1
    )[0]
    send_helper = source.split("async function sendChatMessage", 1)[1].split(
        "async function handleChatImagePicked", 1
    )[0]

    assert "requestAnimationFrame(scrollChatToBottom)" in helper
    assert "setTimeout(scrollChatToBottom, 0)" in helper
    assert 'appendChatMessage("user", message)' in send_helper
    assert 'input.value = ""' in send_helper
    assert "forceScrollChatToBottom()" in send_helper


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
