from __future__ import annotations

from pathlib import Path


RUNTIME_JS = Path("src/Undefined/webui/static/js/runtime.js")
RUNTIME_CSS = Path("src/Undefined/webui/static/css/components.css")
WEBUI_TEMPLATE = Path("src/Undefined/webui/templates/index.html")
MAIN_JS = Path("src/Undefined/webui/static/js/main.js")
API_JS = Path("src/Undefined/webui/static/js/api.js")
APP_CSS = Path("src/Undefined/webui/static/css/app.css")
RESPONSIVE_CSS = Path("src/Undefined/webui/static/css/responsive.css")
I18N_JS = Path("src/Undefined/webui/static/js/i18n.js")
WEBUI_APP_PY = Path("src/Undefined/webui/app.py")
TAURI_CONF = Path("apps/undefined-console/src-tauri/tauri.conf.json")


def test_webchat_frontend_reuses_job_message_for_final_message() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")

    assert "activeChatMessageId" in source
    assert 'if (event === "message")' in source
    message_branch = source.split('if (event === "message")', 1)[1].split(
        'if (event === "done")', 1
    )[0]

    assert "ensureStreamingMessage(eventJobId)" in message_branch
    assert 'appendChatMessage("bot", content)' not in message_branch


def test_webchat_html_preview_csp_allows_inline_scripts_without_eval() -> None:
    webui_app = WEBUI_APP_PY.read_text(encoding="utf-8")
    tauri_conf = TAURI_CONF.read_text(encoding="utf-8")

    assert "\"script-src 'self' 'unsafe-inline'; \"" in webui_app
    assert "script-src 'self' 'unsafe-inline';" in tauri_conf
    assert "unsafe-eval" not in webui_app
    assert "unsafe-eval" not in tauri_conf


def test_webchat_frontend_handles_tool_lifecycle_and_webchat_hints() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")

    assert 'event === "token_delta"' not in source
    assert 'event === "tool_delta"' not in source
    assert "pendingToolDeltas" not in source
    assert "appendTokenDelta" not in source
    assert "consumeSse" not in source
    assert "attachChatJobSse" not in source
    assert "text/event-stream" not in source
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
    assert "function updateChatStageDisplay" in source
    assert "function refreshActiveChatTimers" in source
    assert "updateToolDurationDisplay(block)" in source
    assert "formatDurationMs" in source
    assert "payload && payload.elapsed_ms" in source
    assert "Date.now() - runtimeState.activeStageStartedAt" not in source
    assert "runtime.chat_stage_waiting_model" in i18n
    assert "runtime.chat_stage_searching_cognitive_memory" in i18n
    assert ".runtime-chat-stage" in css
    assert "runtime-chat-stage-pulse" not in css


def test_webchat_frontend_has_conversation_sidebar() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    template = WEBUI_TEMPLATE.read_text(encoding="utf-8")
    app_css = APP_CSS.read_text(encoding="utf-8")
    responsive_css = RESPONSIVE_CSS.read_text(encoding="utf-8")
    i18n = I18N_JS.read_text(encoding="utf-8")

    assert "runtimeChatConversations" in template
    assert "btnRuntimeChatNew" in template
    assert "btnRuntimeChatClear" not in template
    assert "runtimeChatCurrentTitle" in template
    assert 'id="runtimeChatConversationDrawerToggle"' in template
    assert "runtime-chat-sidebar-tab" in template
    assert "runtime-chat-sidebar-panel" in template
    assert "loadChatConversations" in source
    assert "switchChatConversation" in source
    assert "renameChatConversation" in source
    assert "deleteChatConversation" in source
    assert "/api/runtime/chat/conversations" in source
    assert ".runtime-chat-sidebar" in app_css
    sidebar_block = app_css.split(".runtime-chat-sidebar {", 1)[1].split(
        ".runtime-chat-sidebar:hover", 1
    )[0]
    assert "position: absolute;" in sidebar_block
    assert "right: 0;" in sidebar_block
    assert "transform: translateX(calc(100% - 36px));" in sidebar_block
    assert "transition:" in sidebar_block
    assert ".runtime-chat-sidebar:hover" in app_css
    assert ".runtime-chat-sidebar:focus-within" in app_css
    assert "transform: translateX(0);" in app_css
    assert ".runtime-chat-sidebar-tab" in app_css
    assert "runtime-chat-conversation-created" in app_css
    assert ".runtime-chat-conversation.is-new" in app_css
    assert "recentlyCreatedConversationId" in source
    assert 'showToast(t("runtime.chat_conversation_created")' in source
    assert '"runtime.chat_conversation_created"' in i18n
    assert 'get("btnRuntimeChatClear")' not in source
    assert "chatConversationDrawerOpen: false" in source
    assert "function setChatConversationDrawerOpen" in source
    assert "function canToggleChatConversationDrawer" in source
    assert "window.innerWidth <= 768" in source
    assert "runtimeChatConversationDrawerToggle" in source
    assert 'toggle.setAttribute(\n                "aria-expanded",' in source
    mobile_sidebar_block = responsive_css.split(".runtime-chat-sidebar {", 1)[1].split(
        ".runtime-chat-sidebar-panel", 1
    )[0]
    assert "position: static;" in mobile_sidebar_block
    assert "transform: none;" in mobile_sidebar_block
    mobile_panel_block = responsive_css.split(".runtime-chat-sidebar-panel {", 1)[
        1
    ].split(".runtime-chat-sidebar.is-open .runtime-chat-sidebar-panel", 1)[0]
    assert "display: none;" in mobile_panel_block
    assert ".runtime-chat-sidebar.is-open .runtime-chat-sidebar-panel" in responsive_css
    assert "display: block;" in responsive_css
    mobile_tab_block = responsive_css.split(".runtime-chat-sidebar-tab {", 1)[1].split(
        ".runtime-chat-sidebar-tab::after", 1
    )[0]
    assert "display: flex;" in mobile_tab_block
    assert "width: 100%;" in mobile_tab_block
    assert "runtime.chat_new_conversation" in i18n


def test_webchat_frontend_has_slash_command_palette() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    template = WEBUI_TEMPLATE.read_text(encoding="utf-8")
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    responsive_css = RESPONSIVE_CSS.read_text(encoding="utf-8")
    i18n = I18N_JS.read_text(encoding="utf-8")

    assert 'id="runtimeChatCommandPalette"' in template
    input_row = template.split('class="runtime-chat-input-row"', 1)[1].split(
        'id="runtimeChatReferences"',
        1,
    )[0]
    assert input_row.index('id="runtimeChatCommandPalette"') < input_row.index(
        'id="runtimeChatInput"'
    )

    assert "chatCommandsLoaded" in source
    assert "CHAT_COMMAND_CACHE_MS" in source
    assert "CHAT_COMMAND_MAX_MATCHES" in source
    assert '"/api/runtime/commands?scope=webui"' in source
    assert "function buildChatCommandContext" in source
    assert 'if (!beforeCursor.startsWith("/")) return null' in source
    assert "if (tokenCount > 2) return null" in source
    assert 'mode: hasCommandBoundary ? "subcommand" : "command"' in source
    assert "function currentChatCommandMatches" in source
    assert "findChatCommandByNameOrAlias(context.commandQuery)" in source
    assert "function chatCommandDisplayName" in source
    assert "typedCommandName: chatCommandDisplayName(" in source
    assert "const commandName = match.typedCommandName || match.command.name" in source
    assert (
        "if (!command || !subcommands.length) {\n                return [];" in source
    )
    assert "function replaceChatCommandInput" in source
    assert "chooseActiveChatCommandMatch()" in source
    assert 'event.key === "ArrowDown"' in source
    assert 'event.key === "ArrowUp"' in source
    assert 'event.key === "Tab"' in source
    assert 'event.key === "Escape"' in source
    assert "data-command-match-index" in source
    assert "closeChatCommandPalette()" in source

    assert ".runtime-chat-command-palette" in css
    palette_block = css.split(".runtime-chat-command-palette {", 1)[1].split(
        ".runtime-chat-command-palette.is-open",
        1,
    )[0]
    assert "position: absolute;" in palette_block
    assert "bottom: calc(100% + 10px);" in palette_block
    assert "max-height: min(360px, 46vh);" in palette_block
    assert ".runtime-chat-command-item" in css
    assert ".runtime-chat-command-side code" in css
    assert ".runtime-chat-command-palette" in responsive_css
    assert "grid-template-columns: minmax(0, 1fr);" in responsive_css
    assert "runtime.chat_command_hint" in i18n
    assert "runtime.chat_command_hint_subcommand" in i18n
    assert "runtime.chat_command_empty" in i18n
    assert "runtime.chat_command_subcommands" in i18n


def test_webchat_frontend_sends_conversation_id_with_history_and_jobs() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")

    assert "currentChatConversationId" in source
    assert 'chatUrl("/api/runtime/chat/history"' in source
    assert 'chatUrl("/api/runtime/chat/jobs/active"' in source
    assert "runtimeChatJobEventsUrls" in source
    assert "conversation_id: currentChatConversationId()" in source
    assert "activeJobConversationId" in source
    assert (
        "runtimeState.activeJobConversationId || currentChatConversationId()" in source
    )
    assert "eventConversationId === currentChatConversationId()" in source
    assert "jobConversationId !== currentChatConversationId()" in source


def test_webchat_frontend_resumes_backend_job_after_refresh_or_reconnect() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    history_helper = source.split("async function loadChatHistory", 1)[1].split(
        "async function loadOlderChatHistory",
        1,
    )[0]
    conversation_helper = source.split(
        "async function loadChatConversations",
        1,
    )[1].split("async function createChatConversation", 1)[0]
    resume_helper = source.split("async function resumeActiveChatJob", 1)[1].split(
        "async function clearChatHistory",
        1,
    )[0]

    assert "{ resumeActiveJob = true }" in history_helper
    assert "if (runtimeState.chatHistoryLoaded && !force)" in history_helper
    assert "await resumeActiveChatJob();" in history_helper
    assert "const localJobId = runtimeState.activeJobId" in resume_helper
    assert 'chatUrl("/api/runtime/chat/jobs/active")' in resume_helper
    assert "attachChatJob(jobId, runtimeState.lastEventSeq)" in resume_helper
    assert "runtimeState.activeJobId) return" not in resume_helper
    assert "await loadChatHistory(true, { resumeActiveJob: false })" in resume_helper
    assert "runtimeState.chatBusy = false" in resume_helper
    assert "const previousJobId = runtimeState.activeJobId" in conversation_helper
    assert 'const nextJobId = String(activeJob.job_id || "")' in conversation_helper
    assert "previousJobId !== nextJobId" in conversation_helper
    assert "localJobId !== jobId" in resume_helper
    assert "runtimeState.lastEventSeq = 0" in conversation_helper
    assert "clearToolCollapseTimers()" in conversation_helper
    assert 'window.addEventListener(\n                "online"' in source


def test_webchat_frontend_lazy_load_preserves_scroll_offset() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    older_helper = source.split("async function loadOlderChatHistory", 1)[1].split(
        "function applyChatEvent",
        1,
    )[0]

    assert "const previousHeight = log.scrollHeight" in older_helper
    assert "const previousTop = log.scrollTop" in older_helper
    assert "appendHistoryChatItem(items[idx], {" in older_helper
    assert "prepend: true" in older_helper
    assert (
        "log.scrollTop = previousTop + (log.scrollHeight - previousHeight)"
        in older_helper
    )


def test_webchat_frontend_keeps_final_duration_after_done() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")

    done_branch = source.split('if (event === "done")', 1)[1].split(
        'if (event === "error")', 1
    )[0]
    finalize_helper = source.split("function finalizeActiveChatMessage", 1)[1].split(
        "function chatStageLabel", 1
    )[0]
    history_helper = source.split("function appendHistoryChatItem", 1)[1].split(
        "function clearChatMessages", 1
    )[0]

    assert "finalizeActiveChatMessage(payload || {})" in done_branch
    assert "payload && payload.duration_ms" in finalize_helper
    assert 'stage: "done"' in finalize_helper
    assert "final: true" in finalize_helper
    assert "webchat.duration_ms" in history_helper
    assert "setChatStage(message, {" in history_helper


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
    assert "function renderToolNodeIfChanged" in source
    assert "node.dataset.renderSignature === nextSignature" in source
    assert "updateToolMetaDisplay(block)" in source
    assert "data-tool-status-for" in source


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


def test_webchat_tool_snapshots_do_not_rerender_unchanged_blocks() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    live_update_helper = source.split("function upsertTimelineToolBlock", 1)[1].split(
        "function appendNestedTimelineMessage", 1
    )[0]
    agent_stage_helper = source.split("function upsertAgentStageBlock", 1)[1].split(
        "function historyWebchatEvents",
        1,
    )[0]
    history_helper = source.split("function renderHistoryTimeline", 1)[1].split(
        "function appendHistoryChatItem",
        1,
    )[0]

    assert "previousParentSignature === nextParentSignature" in live_update_helper
    assert "previousRootSignature === nextRootSignature" in live_update_helper
    assert 'status === "tool_snapshot"' in live_update_helper
    assert "renderToolNodeIfChanged(parentNode, parent)" in live_update_helper
    assert "renderToolNodeIfChanged(rootNode, root)" in live_update_helper
    assert "renderToolNodeIfChanged(node, block)" in live_update_helper
    assert "previousParentSignature === nextParentSignature" in agent_stage_helper
    assert "renderToolNodeIfChanged(node, block)" in agent_stage_helper
    assert "node.innerHTML = renderToolBlock" not in live_update_helper
    assert "node.innerHTML = renderToolBlock" not in agent_stage_helper
    assert "node.innerHTML = renderToolBlock" in history_helper


def test_webchat_frontend_updates_agent_stage_summary_without_timeline_noise() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    css = RUNTIME_CSS.read_text(encoding="utf-8")

    assert 'event === "agent_stage"' in source
    assert "function upsertAgentStageBlock" in source
    assert "function reduceAgentStageBlock" in source
    assert "currentStage" in source
    assert "current_stage_elapsed_ms" in source
    render_helper = source.split("function renderToolTimelineItem", 1)[1].split(
        "function toolBlockKey", 1
    )[0]
    reduce_helper = source.split("function reduceAgentStageBlock", 1)[1].split(
        "function agentStageRenderSignature", 1
    )[0]

    assert 'entry.type === "stage"' in render_helper
    assert 'return "";' in render_helper
    assert 'type: "stage"' not in reduce_helper
    assert "function agentStageRenderSignature" in source
    assert "previousSignature === agentStageRenderSignature(block)" in source
    assert "currentStage: stage || previous.currentStage" in source
    assert "runtime-tool-stage" not in source
    assert ".runtime-tool-stage" not in css


def test_webchat_frontend_polls_job_events_incrementally() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")

    assert "function pollChatJob" in source
    assert "CHAT_POLL_INTERVAL_MS = 500" in source
    assert "CHAT_CLOCK_INTERVAL_MS = 500" in source
    assert 'format: "json"' in source
    assert "after: String(runtimeState.lastEventSeq)" in source
    assert "function applyChatEventsPayload" in source
    assert "function applyChatJobSnapshot" in source
    assert "job.current_tool_calls" in source
    assert "upsertToolSnapshot" in source
    assert "runtimeState.chatPollTimer" in source
    assert "runtimeState.chatPollBackoffMs" in source
    assert "pollChatJob(jobId).catch" in source
    assert 'Accept: "text/event-stream"' not in source


def test_webchat_frontend_retries_active_job_resume_after_refresh_failure() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    resume_helper = source.split("async function resumeActiveChatJob", 1)[1].split(
        "async function clearChatHistory", 1
    )[0]

    assert "activeJobResumeTimer" in source
    assert "ACTIVE_JOB_RESUME_MAX_ATTEMPTS = 20" in source
    assert "runtimeState.activeJobResumeAttempts += 1" in resume_helper
    assert "setTimeout(() => {" in resume_helper
    assert "resumeActiveChatJob().catch" in resume_helper
    assert 'window.addEventListener(\n                "online"' in source


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
    assert "runtime-tool-duration" in render_helper
    assert "runtime-tool-status" in render_helper
    assert "runtime-tool-kind" in render_helper
    assert (
        render_helper.index("runtime-tool-name")
        < render_helper.index("runtime-tool-duration")
        < render_helper.index("runtime-tool-status")
        < render_helper.index("runtime-tool-kind")
    )
    assert "grid-template-columns: auto minmax(0, 1fr) auto auto;" in summary_css
    assert "min-height: 32px;" in summary_css
    assert "padding: 3px 10px 3px 13px;" in summary_css
    assert "line-height: 1.2;" in summary_css
    name_css = css.split(".runtime-tool-block summary .runtime-tool-name", 1)[1].split(
        ".runtime-tool-block summary .runtime-tool-duration", 1
    )[0]
    duration_css = css.split(".runtime-tool-block summary .runtime-tool-duration", 1)[
        1
    ].split(".runtime-tool-block summary .runtime-tool-status", 1)[0]
    assert "font-weight: 650;" in name_css
    assert "font-family: var(--font-mono);" in duration_css
    assert "white-space: nowrap;" in duration_css


def test_webchat_tool_blocks_auto_collapse_after_minimum_visible_time() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    assert "TOOL_AUTO_COLLAPSE_MIN_VISIBLE_MS = 2000" in source
    assert "runtimeState.toolCollapseTimers" in source
    assert "function scheduleToolAutoCollapse" in source
    assert 'block.autoOpen ? " open" : ""' in source
    assert "autoOpen: isStart || isSnapshot ? true : !!previous.autoOpen" in source
    assert "localStartedAtMs: isStart" in source
    assert "finishedAtMs: isEnd" in source
    signature_helper = source.split("function toolRenderSignature", 1)[1].split(
        "function updateToolMetaDisplay",
        1,
    )[0]
    assert "block.autoOpen" in signature_helper
    assert "const childSignature" in signature_helper
    assert "block.children.map(toolRenderSignature)" in signature_helper
    assert "const timelineSignature" in signature_helper
    assert "`call:${toolRenderSignature(entry.call)}`" in signature_helper
    collapse_helper = source.split("function scheduleToolAutoCollapse", 1)[1].split(
        "function upsertTimelineToolBlock", 1
    )[0]
    assert "latest.autoOpen = false" in collapse_helper
    assert "redrawToolTimelineNode(item, blocks, timerKey)" in collapse_helper
    assert "setTimeout(collapse, TOOL_AUTO_COLLAPSE_MIN_VISIBLE_MS)" in collapse_helper
    assert "TOOL_AUTO_COLLAPSE_MIN_VISIBLE_MS -" not in collapse_helper
    clear_helper = source.split("function clearToolCollapseTimers", 1)[1].split(
        "function finishStreamingMessage", 1
    )[0]
    assert "clearTimeout(timer)" in clear_helper


def test_webchat_auto_scroll_toggle_controls_stream_scroll() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    template = Path("src/Undefined/webui/templates/index.html").read_text(
        encoding="utf-8"
    )
    css = RUNTIME_CSS.read_text(encoding="utf-8")

    assert "runtimeChatAutoScroll" in template
    assert "runtime.chat_auto_scroll" in template
    assert "CHAT_AUTO_SCROLL_STORAGE_KEY" in source
    assert "readChatAutoScrollPreference()" in source
    assert "setChatAutoScroll(autoScrollToggle.checked)" in source
    assert "if (!runtimeState.chatAutoScroll) return;" in source
    assert "forceScrollChatToBottom()" in source
    assert "prefersReducedMotion()" in source
    assert "chatScrollBehavior()" in source
    assert "behavior: chatScrollBehavior()" in source
    assert ".toggle-input:focus-visible + .toggle-track" in css
    assert ".toggle-input { display: none;" not in css


def test_webchat_tab_activation_forces_bottom_scroll_after_history_load() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    load_helper = source.split("async function loadChatHistory", 1)[1].split(
        "async function loadOlderChatHistory", 1
    )[0]
    tab_helper = source.split("function onTabActivated", 1)[1].split(
        "window.RuntimeController", 1
    )[0]
    chat_branch = tab_helper.split('if (tab === "chat")', 1)[1].split(
        "return;",
        1,
    )[0]

    assert "forceScrollChatToBottomSoon()" in load_helper
    assert "forceScrollChatToBottom();" not in load_helper
    assert "loadChatConversations()" in chat_branch
    assert ".then(() => loadChatHistory())" in chat_branch
    assert "forceScrollChatToBottomSoon()" in chat_branch
    assert "CHAT_TOP_LOAD_SUPPRESS_MS = 900" in source
    assert "suppressChatTopHistoryLoad()" in source
    assert "isChatTopHistoryLoadSuppressed()" in source
    assert "chatTopLoadSuppressedUntil" in source


def test_webchat_frontend_renders_tool_duration() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")

    assert "block.durationMs" in source
    assert "payload.duration_ms" in source
    assert "runtime-tool-duration" in source
    assert "formatDurationMs(runningDurationMs(block))" in source
    assert "function runningDurationMs" in source
    assert "function backendDurationClock" in source
    assert "function updateToolDurationDisplay" in source
    assert "function toolRenderSignature" in source
    assert "durationBaseMs" in source
    assert "durationReceivedAtMs" in source
    assert "statusLabel} · ${durationLabel}" not in source


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


def test_webchat_frontend_sanitizes_markdown_html_and_unsafe_links() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    render_helper = source.split("function createSafeMarkedRenderer", 1)[1].split(
        "function renderChatContent", 1
    )[0]
    sanitizer_helper = source.split("function sanitizeHtmlSnippet", 1)[0].split(
        "function isSafeRenderedImageUrl", 1
    )[1]

    assert "renderer.html" in render_helper
    assert 'sanitizeHtmlSnippet(text || "")' in render_helper
    assert "SAFE_HTML_TAGS" in sanitizer_helper
    assert "DROP_HTML_TAGS" in sanitizer_helper
    assert 'name.startsWith("on")' in sanitizer_helper
    assert 'name === "style"' in sanitizer_helper
    assert "isSafeRenderedUrl(attr.value)" in sanitizer_helper
    assert "isSafeRenderedImageUrl(attr.value)" in sanitizer_helper
    assert 'element.setAttribute("rel", "noreferrer")' in sanitizer_helper
    assert 'element.setAttribute("loading", "lazy")' in sanitizer_helper
    assert "isSafeRenderedUrl(href)" in render_helper
    assert 'rel="noreferrer"' in render_helper
    assert "renderer.image" in render_helper
    assert "renderer: createSafeMarkedRenderer()" in source


def test_webchat_markdown_quotes_render_as_collapsible_scroll_blocks() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    renderer_helper = source.split("function createSafeMarkedRenderer", 1)[1].split(
        "renderer.link",
        1,
    )[0]
    append_helper = source.split("function appendChatMessage", 1)[1].split(
        "function formatDurationMs",
        1,
    )[0]
    update_helper = source.split("function updateChatMessage", 1)[1].split(
        "function currentChatJobId",
        1,
    )[0]
    quote_css = css.split(".runtime-quote-block", 1)[1].split(
        ".runtime-chat-content.markdown table",
        1,
    )[0]

    assert "function hasMarkdownBlockquote" in source
    assert "function shouldRenderChatMarkdown" in source
    assert 'role !== "user" || hasMarkdownBlockquote(content)' in source
    assert "renderer.blockquote = ({ tokens }) =>" in renderer_helper
    assert '<details class="runtime-quote-block">' in renderer_helper
    assert '<div class="runtime-quote-body">' in renderer_helper
    assert "shouldRenderChatMarkdown(role, content)" in append_helper
    assert "renderChatContent(content, useMarkdown)" in append_helper
    assert 'contentEl.classList.toggle("markdown", useMarkdown)' in update_helper
    assert "max-height: min(28vh, 220px);" in quote_css
    assert "overflow: auto;" in quote_css
    assert ".runtime-quote-block[open] summary::before" in css


def test_webchat_frontend_renders_standalone_html_without_markdown_code_blocks() -> (
    None
):
    source = RUNTIME_JS.read_text(encoding="utf-8")
    render_helper = source.split("function renderChatContent", 1)[1].split(
        "function readFileAsDataUrl", 1
    )[0]
    sanitizer_section = source.split("const SAFE_HTML_TAGS", 1)[1].split(
        "const CODE_LANGUAGE_ALIASES", 1
    )[0]

    assert "function looksLikeStandaloneHtml" in source
    assert "STANDALONE_HTML_ROOT_TAGS" in source
    assert "looksLikeStandaloneHtml(processed)" in render_helper
    assert "html = sanitizeHtmlSnippet(processed)" in render_helper
    assert '"head"' in sanitizer_section
    assert '"title"' in sanitizer_section
    assert '"style"' in sanitizer_section


def test_webchat_frontend_highlights_markdown_code_blocks() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    template = WEBUI_TEMPLATE.read_text(encoding="utf-8")

    assert "function highlightCodeBlock" in source
    assert 'typeof hljs === "undefined"' in source
    assert "hljs.getLanguage(lang)" in source
    assert "hljs.highlight(code, {" in source
    assert "hljs.highlightAuto(code).value" in source
    assert "renderer.code" in source
    assert "runtime-code-block" in source
    assert "runtime-code-toolbar" in source
    assert "runtime-code-action" in source
    assert "CODE_COLLAPSE_LINE_THRESHOLD = 8" in source
    assert "function shouldCollapseCodeBlock" in source
    assert "function toggleCodeBlock" in source
    assert "data-code-toggle" in source
    assert "runtime.expand_code" in source
    assert "runtime.collapse_code" in source
    assert "data-code-copy" in source
    assert "data-code-run-html" in source
    assert "function isRunnableHtmlCode" in source
    assert "function copyCodeBlock" in source
    assert "function runHtmlCodeBlock" in source
    assert "navigator.clipboard.writeText" in source
    assert 'document.execCommand("copy")' in source
    assert 'chatLog.addEventListener("click"' in source
    assert 'target.closest("[data-code-toggle]")' in source
    assert "highlightCodeBlock(codeText, normalizedLanguage)" in source
    assert "language-${escapeHtml(normalizedLanguage)}" in source
    assert 'runtime.copy_code": "复制"' in I18N_JS.read_text(encoding="utf-8")
    assert 'runtime.run_html": "运行"' in I18N_JS.read_text(encoding="utf-8")
    assert 'runtime.expand_code": "展开"' in I18N_JS.read_text(encoding="utf-8")
    assert 'runtime.collapse_code": "折叠"' in I18N_JS.read_text(encoding="utf-8")
    assert "/static/js/vendor/highlight.min.js" in template
    assert "/static/css/highlight-github.min.css" in template
    assert Path("src/Undefined/webui/static/js/vendor/highlight.min.js").is_file()
    assert Path("src/Undefined/webui/static/js/vendor/highlightjs.LICENSE").is_file()
    assert Path("src/Undefined/webui/static/css/highlight-github.min.css").is_file()

    assert ".runtime-code-toolbar" in css
    assert (
        "position: sticky;"
        in css.split(".runtime-code-toolbar", 1)[1].split(
            ".runtime-code-language",
            1,
        )[0]
    )
    assert ".runtime-code-language" in css
    assert ".runtime-code-action" in css
    assert ".runtime-code-action.primary" in css
    assert ".runtime-code-block.is-collapsed .runtime-code-body" in css
    assert ".runtime-code-block.is-collapsed .runtime-code-body::after" in css
    content_css = css.split(".runtime-chat-content {", 1)[1].split(
        ".runtime-chat-timeline",
        1,
    )[0]
    table_css = css.split(".runtime-chat-content.markdown table", 1)[1].split(
        ".runtime-chat-content.markdown th",
        1,
    )[0]
    pre_css = css.split(".runtime-chat-content.markdown pre {", 1)[1].split(
        ".runtime-chat-content.markdown pre code",
        1,
    )[0]
    code_css = css.split(".runtime-chat-content.markdown pre code {", 1)[1].split(
        ".runtime-chat-content.markdown pre code.hljs",
        1,
    )[0]
    assert "max-width: 100%;" in content_css
    assert "overflow-wrap: anywhere;" in content_css
    assert "table-layout: fixed;" in table_css
    assert "overflow-x: hidden;" in pre_css
    assert "white-space: pre-wrap;" in pre_css
    assert "white-space: pre-wrap;" in code_css
    assert "overflow-wrap: anywhere;" in code_css
    collapsed_css = css.split(
        ".runtime-code-block.is-collapsed .runtime-code-body",
        1,
    )[1].split(
        ".runtime-code-block.is-collapsed .runtime-code-body::after",
        1,
    )[0]
    collapsed_after_css = css.split(
        ".runtime-code-block.is-collapsed .runtime-code-body::after",
        1,
    )[1].split(".runtime-chat-content.markdown pre", 1)[0]
    assert "height: 9.2em;" in collapsed_css
    assert "overflow: auto;" in collapsed_css
    assert "scrollbar-gutter: stable;" in collapsed_css
    assert "display: none;" in collapsed_after_css
    assert ".runtime-chat-content.markdown pre code.hljs" in css
    assert ".runtime-code-block .hljs-keyword" in css
    assert ".runtime-code-block .hljs-string" in css
    assert ".runtime-code-block .hljs-comment" in css
    assert ".runtime-code-block .hljs-number" in css
    assert ".runtime-code-block .hljs-title.function_" in css
    assert ".runtime-code-block .hljs-property" in css
    assert '[data-theme="dark"] .runtime-code-block' in css


def test_webchat_html_runner_runs_code_in_sandboxed_preview() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    responsive_css = RESPONSIVE_CSS.read_text(encoding="utf-8")
    template = WEBUI_TEMPLATE.read_text(encoding="utf-8")
    i18n = I18N_JS.read_text(encoding="utf-8")

    assert 'id="runtimeHtmlRunner"' in template
    assert 'id="runtimeHtmlRunnerFrame"' in template
    assert 'sandbox="allow-scripts allow-forms allow-modals"' in template
    assert "allow-same-origin" not in template
    assert 'id="btnRuntimeHtmlPick"' in template
    assert 'id="btnRuntimeHtmlClose"' in template
    assert 'id="runtimeHtmlRunnerResize"' in template
    assert "runtime.html_runner" in template

    assert "htmlRunnerSource" in source
    assert "htmlRunnerPickMode" in source
    assert "htmlRunnerResize" in source
    assert "htmlRunnerDrag" in source
    assert "HTML_RUNNER_MIN_WIDTH = 360" in source
    assert "HTML_RUNNER_MIN_HEIGHT = 280" in source
    assert "const minWidth = Math.min(HTML_RUNNER_MIN_WIDTH, viewportWidth)" in source
    assert (
        "const minHeight = Math.min(HTML_RUNNER_MIN_HEIGHT, viewportHeight)" in source
    )
    assert "function buildHtmlRunnerDocument" in source
    assert "function htmlRunnerPickerScript" in source
    assert "function injectHtmlRunnerPicker" in source
    assert "function syncHtmlRunnerPickModeToFrame" in source
    assert "function setHtmlRunnerPickMode" in source
    assert "function clampHtmlRunnerPosition" in source
    assert "function setHtmlRunnerRect" in source
    assert "function setHtmlRunnerSize" in source
    assert "function clearHtmlRunnerInteraction" in source
    assert "function ensureHtmlRunnerInitialRect" in source
    assert "function startHtmlRunnerResize" in source
    assert "function moveHtmlRunnerResize" in source
    assert "function stopHtmlRunnerResize" in source
    assert "function startHtmlRunnerDrag" in source
    assert "function moveHtmlRunnerDrag" in source
    assert "function stopHtmlRunnerDrag" in source
    assert "function clampVisibleHtmlRunner" in source
    assert "function openHtmlRunner" in source
    assert "function closeHtmlRunner" in source
    assert "function handleHtmlRunnerPicked" in source
    assert (
        'const confirmHint = JSON.stringify(t("runtime.html_pick_confirm_hint"))'
        in source
    )
    assert "let locked = null;" in source
    assert "if (locked) return;" in source
    assert "if (!locked) {" in source
    assert (
        "locked = selected || candidateFromPoint(event.clientX, event.clientY)"
        in source
    )
    assert "return;\n    }\n    const target = locked;" in source
    assert "clearHtmlRunnerInteraction()" in source
    assert "ensureHtmlRunnerInitialRect(runner)" in source
    assert "frame.srcdoc = injectHtmlRunnerPicker(html)" in source
    assert (
        "sanitizeHtmlSnippet"
        not in source.split(
            "function buildHtmlRunnerDocument",
            1,
        )[1].split("function htmlRunnerPickerScript", 1)[0]
    )
    assert 'parent.postMessage({ type: "webui-html-picked", html }, "*")' in source
    assert "data-webui-html-picker-overlay" in source
    assert "data-webui-html-picker-label" in source
    assert "data-webui-html-picking" in source
    assert "document.elementsFromPoint" in source
    assert "candidateFromPoint(event.clientX, event.clientY)" in source
    assert 'document.addEventListener("pointerdown"' in source
    assert 'parent.postMessage({ type: "webui-html-picker-ready" }, "*")' in source
    assert "requestAnimationFrame(() =>" in source
    assert "elementLabel(element)" in source
    assert "event.source !== frame.contentWindow" in source
    assert 'data.type === "webui-html-picker-ready"' in source
    assert 'data.type !== "webui-html-picked"' in source
    assert "btnRuntimeHtmlClose" in source
    assert "btnRuntimeHtmlPick" in source
    assert "runtimeHtmlRunnerResize" in source
    assert ".runtime-html-runner-toolbar" in source
    assert "setHtmlRunnerPickMode(!runtimeState.htmlRunnerPickMode)" in source
    assert "syncHtmlRunnerPickModeToFrame()" in source
    assert "startHtmlRunnerResize" in source
    assert "moveHtmlRunnerResize" in source
    assert "stopHtmlRunnerResize" in source
    assert "startHtmlRunnerDrag" in source
    assert "moveHtmlRunnerDrag" in source
    assert "stopHtmlRunnerDrag" in source
    assert '"lostpointercapture"' in source
    assert 'window.addEventListener("pointerup"' in source
    assert 'window.addEventListener("pointercancel"' in source
    assert 'window.addEventListener("blur"' in source
    assert "setHtmlRunnerRect(rect.left, rect.top, rect.width, rect.height)" in source
    assert 'window.addEventListener("resize", clampVisibleHtmlRunner)' in source
    assert "setPointerCapture(pointerId)" in source
    assert "releasePointerCapture(state.pointerId)" in source
    assert 'button.setAttribute("aria-pressed", active ? "true" : "false")' in source

    assert ".runtime-html-runner" in css
    assert ".runtime-html-runner-panel" in css
    assert ".runtime-html-runner-toolbar" in css
    assert ".runtime-html-runner-frame" in css
    runner_css = css.split(".runtime-html-runner {", 1)[1].split(
        ".runtime-html-runner[hidden]",
        1,
    )[0]
    runner_panel_css = css.split(".runtime-html-runner-panel {", 1)[1].split(
        ".runtime-html-runner-toolbar",
        1,
    )[0]
    assert "resize: both;" not in runner_css
    assert "right:" not in runner_css
    assert "bottom:" not in runner_css
    assert "overflow: visible;" in runner_css
    assert "pointer-events: auto;" in runner_css
    assert "height: 360px;" in runner_css
    assert "grid-template-rows: auto minmax(0, 1fr);" in runner_panel_css
    assert "width: 100%;" in runner_panel_css
    assert "height: 100%;" in runner_panel_css
    assert ".runtime-html-runner-resize" in css
    assert ".runtime-html-runner.is-resizing" in css
    assert ".runtime-html-runner.is-dragging" in css
    assert (
        "pointer-events: none;"
        in css.split(
            ".runtime-html-runner.is-resizing .runtime-html-runner-frame",
            1,
        )[1].split(".runtime-html-runner-toolbar", 1)[0]
    )
    assert (
        "pointer-events: none;"
        in css.split(
            ".runtime-html-runner.is-dragging .runtime-html-runner-frame",
            1,
        )[1].split(".runtime-html-runner-toolbar", 1)[0]
    )
    toolbar_css = css.split(".runtime-html-runner-toolbar {", 1)[1].split(
        ".runtime-html-runner-actions",
        1,
    )[0]
    assert "cursor: move;" in toolbar_css
    assert "touch-action: none;" in toolbar_css
    assert ".runtime-html-runner-actions,\n.runtime-html-runner-actions *" in css
    assert ".runtime-html-runner-actions button" in css
    assert ".runtime-html-runner-btn.is-active" in css
    assert ".runtime-html-runner.is-picking .runtime-html-runner-panel" in css
    assert "@keyframes runtime-html-runner-in" in css
    assert ".runtime-html-runner" in responsive_css
    responsive_runner_css = responsive_css.split(".runtime-html-runner {", 1)[1].split(
        ".runtime-html-runner-panel", 1
    )[0]
    assert "right:" not in responsive_runner_css
    assert "bottom:" not in responsive_runner_css
    assert (
        "max-height: calc(100dvh - 24px - env(safe-area-inset-bottom));"
        in responsive_css
    )
    responsive_toolbar_css = responsive_css.split(
        ".runtime-html-runner-toolbar",
        1,
    )[1].split(".runtime-html-runner-title", 1)[0]
    responsive_title_css = responsive_css.split(".runtime-html-runner-title", 1)[
        1
    ].split(".runtime-html-runner-meta", 1)[0]
    responsive_meta_css = responsive_css.split(".runtime-html-runner-meta", 1)[1].split(
        ".runtime-html-runner-actions", 1
    )[0]
    assert "flex-wrap: wrap;" in responsive_toolbar_css
    assert "flex: 1 1 min(160px, 100%);" in responsive_title_css
    assert "max-width: min(62vw, 260px);" in responsive_meta_css
    assert "runtime.html_ready" in i18n
    assert "runtime.pick_html" in i18n
    assert "runtime.html_pick_confirm_hint" in i18n


def test_webchat_references_are_prepended_as_markdown_quotes() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    responsive_css = RESPONSIVE_CSS.read_text(encoding="utf-8")
    template = WEBUI_TEMPLATE.read_text(encoding="utf-8")
    i18n = I18N_JS.read_text(encoding="utf-8")

    assert "chatReferences: []" in source
    assert "chatReferenceSeq" in source
    assert "function addChatReference" in source
    assert "function renderPendingChatReferences" in source
    assert "function formatChatReferencesAsMarkdown" in source
    assert "function buildChatMessageWithReferences" in source
    assert "function chatMessageTextForQuote" in source
    assert "[`> ${label}:`, ...lines.map((line) => `> ${line}`)]" in source
    assert (
        "buildChatMessageWithReferences(\n            message,\n            references"
        in source
    )
    assert "clearChatReferences()" in source
    assert 'addChatReference({ type: "html", text: picked })' in source
    assert 'addChatReference({ type: "message", text })' in source
    assert 'addChatReference({ type: "selection", text })' in source
    assert "runtimeState.chatReferences =" in source
    assert "runtimeState.chatReferences.filter" in source
    assert 'api("/api/runtime/chat/files"' in source

    send_helper = source.split("async function sendChatMessage", 1)[1].split(
        "function handleChatFilesPicked",
        1,
    )[0]
    assert "const references = [...runtimeState.chatReferences]" in send_helper
    assert (
        "if (!message && !attachments.length && !references.length) return"
        in send_helper
    )
    assert "clearChatReferences()" in send_helper

    assert 'id="runtimeChatReferences"' in template
    input_row = template.split('class="runtime-chat-input-row"', 1)[1].split(
        'class="runtime-chat-actions"',
        1,
    )[0]
    assert input_row.index('id="runtimeChatInput"') < input_row.index(
        'id="runtimeChatReferences"'
    )

    assert ".runtime-chat-references" in css
    assert ".runtime-chat-reference" in css
    assert ".runtime-chat-reference-remove" in css
    assert ".runtime-chat-quote-btn" in css
    assert ".runtime-chat-selection-quote" in css
    assert "@keyframes runtime-chat-selection-quote-in" in css
    assert ".runtime-chat-references" in responsive_css
    assert "runtime.reference_added" in i18n
    assert "runtime.reference_html" in i18n
    assert "runtime.quote_selection" in i18n


def test_webchat_tool_status_colors_drive_left_bar_and_status_text() -> None:
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    running_block = css.split(".runtime-tool-block.running {", 1)[1].split(
        ".runtime-tool-block.done", 1
    )[0]
    done_block = css.split(".runtime-tool-block.done {", 1)[1].split(
        ".runtime-tool-block.error", 1
    )[0]
    error_accent_block = css.split(".runtime-tool-block.error {", 1)[1].split(
        ".runtime-tool-block.cancelled", 1
    )[0]
    pseudo_block = css.split(".runtime-tool-block::before", 1)[1].split(
        ".runtime-tool-block.is-agent", 1
    )[0]
    status_block = css.split(
        ".runtime-tool-block.error summary .runtime-tool-status", 1
    )[1].split(".runtime-tool-preview", 1)[0]

    assert "--tool-accent: color-mix(in srgb, var(--warning)" in running_block
    assert "--tool-accent: var(--success);" in done_block
    assert "--tool-accent: var(--error);" in error_accent_block
    assert "background: var(--tool-accent);" in pseudo_block
    assert ".runtime-tool-block.running summary .runtime-tool-status" in css
    assert ".runtime-tool-block.done summary .runtime-tool-status" in css
    assert "color: var(--error);" in status_block
    assert ".runtime-tool-block.cancelled summary .runtime-tool-status" in status_block
    assert "var(--danger)" not in status_block


def test_webchat_send_scrolls_to_bottom_after_layout_updates() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    force_helper = source.split("function forceScrollChatToBottomSoon", 1)[1].split(
        "function scrollChatToBottomSoon", 1
    )[0]
    helper = source.split("function scrollChatToBottomSoon", 1)[1].split(
        "function updateChatMessage", 1
    )[0]
    send_helper = source.split("async function sendChatMessage", 1)[1].split(
        "function handleChatFilesPicked", 1
    )[0]

    assert "requestAnimationFrame(() =>" in force_helper
    assert "requestAnimationFrame(forceScrollChatToBottom)" in force_helper
    assert "setTimeout(forceScrollChatToBottom, 80)" in force_helper
    assert "requestAnimationFrame(scrollChatToBottom)" in helper
    assert "setTimeout(scrollChatToBottom, 0)" in helper
    assert "buildChatMessageWithAttachments(" in send_helper
    assert 'appendChatMessage("user", outboundMessage)' in send_helper
    assert 'input.value = ""' in send_helper
    assert "clearChatAttachments()" in send_helper
    assert "forceScrollChatToBottomSoon()" in send_helper
    assert "ensureStreamingMessage()" in send_helper


def test_webchat_frontend_pastes_files_as_pending_attachments() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    template = WEBUI_TEMPLATE.read_text(encoding="utf-8")
    i18n = I18N_JS.read_text(encoding="utf-8")
    api_source = API_JS.read_text(encoding="utf-8")

    assert "chatAttachments: []" in source
    assert "function addChatFiles" in source
    assert "function renderPendingChatAttachments" in source
    assert "async function uploadChatFile" in source
    assert "async function buildChatMessageWithAttachments" in source
    assert "CHAT_INLINE_IMAGE_MAX_BYTES" in source
    assert "URL.createObjectURL(file)" in source
    assert "URL.revokeObjectURL" in source
    assert "runtime-chat-attachment-thumb" in source
    assert "is-missing-thumb" in source
    assert 'item.kind === "image" ? "IMG" : "FILE"' in source
    assert "CHAT_ATTACHMENT_RAIL_BASE_WIDTH" in source
    assert "CHAT_ATTACHMENT_RAIL_STEP_WIDTH" in source
    assert "CHAT_ATTACHMENT_RAIL_MAX_WIDTH" in source
    assert "CHAT_ATTACHMENT_CARD_MAX_WIDTH" in source
    assert "CHAT_ATTACHMENT_CARD_MIN_WIDTH" in source
    assert "CHAT_ATTACHMENT_COMPRESSED_COUNT" in source
    assert "Math.min(\n                CHAT_ATTACHMENT_RAIL_MAX_WIDTH" in source
    assert '"--chat-attachment-rail-width"' in source
    assert '"--chat-attachment-card-width"' in source
    assert '"is-attachment-rail-full"' in source
    assert '"is-attachment-compressed"' in source
    assert "Math.floor(\n                        (width - Math.max" in source
    assert 'api("/api/runtime/chat/files"' in source
    assert "event.clipboardData && event.clipboardData.files" in source
    assert 'addChatFiles(files, { source: "paste" })' in source
    assert (
        "sendChatMessage()"
        not in source.split('chatInput.addEventListener("paste"', 1)[1].split("});", 1)[
            0
        ]
    )
    assert 'id="runtimeChatAttachments"' in template
    input_row = template.split('class="runtime-chat-input-row"', 1)[1].split(
        'class="runtime-chat-actions"',
        1,
    )[0]
    assert input_row.index('id="runtimeChatInput"') < input_row.index(
        'id="runtimeChatAttachments"'
    )
    assert 'id="runtimeChatFileInput" type="file" multiple hidden' in template
    assert 'data-i18n="runtime.attach_file"' in template
    assert ".runtime-chat-attachments" in css
    input_row_block = css.split(".runtime-chat-input-row {", 1)[1].split(
        ".runtime-chat-input-row > .runtime-chat-input",
        1,
    )[0]
    input_block = css.split(
        ".runtime-chat-input-row > .runtime-chat-input",
        1,
    )[1].split(".runtime-chat-attachments", 1)[0]
    attachments_block = css.split(".runtime-chat-attachments {", 1)[1].split(
        ".runtime-chat-attachments[hidden]",
        1,
    )[0]
    hidden_block = css.split(".runtime-chat-attachments[hidden]", 1)[1].split(
        ".runtime-chat-attachment {",
        1,
    )[0]
    compressed_block = css.split(
        ".runtime-chat-input-row.is-attachment-compressed .runtime-chat-attachment",
        1,
    )[1].split(".runtime-chat-attachment-preview", 1)[0]
    compressed_preview_block = css.split(
        ".runtime-chat-input-row.is-attachment-compressed .runtime-chat-attachment-preview",
        1,
    )[1].split(
        ".runtime-chat-input-row.is-attachment-compressed .runtime-chat-attachment-main",
        1,
    )[0]
    compressed_remove_block = css.split(
        ".runtime-chat-input-row.is-attachment-compressed .runtime-chat-attachment-remove",
        1,
    )[1].split("@keyframes runtime-chat-attachment-in", 1)[0]
    responsive_attachments = (
        RESPONSIVE_CSS.read_text(encoding="utf-8")
        .split(
            ".runtime-chat-attachments",
            1,
        )[1]
        .split(".runtime-chat-attachment", 1)[0]
    )
    mobile_input_row_block = (
        RESPONSIVE_CSS.read_text(encoding="utf-8")
        .split(
            ".runtime-chat-input-row",
            1,
        )[1]
        .split(".runtime-chat-references", 1)[0]
    )
    assert "--chat-attachment-rail-width: 0px;" in input_row_block
    assert "--chat-attachment-card-width: 132px;" in input_row_block
    assert "--chat-attachment-gap: 8px;" in input_row_block
    assert "display: flex;" in input_row_block
    assert "flex: 1 1 auto;" in input_block
    assert "min-width: min(100%, 260px);" in input_block
    assert "height: 54px;" in attachments_block
    assert "flex: 0 0 var(--chat-attachment-rail-width);" in attachments_block
    assert "width: var(--chat-attachment-rail-width);" in attachments_block
    assert "max-width: var(--chat-attachment-rail-width);" in attachments_block
    assert "overflow-x: auto;" in attachments_block
    assert "overflow-y: hidden;" in attachments_block
    assert "scrollbar-width: none;" in attachments_block
    assert "display: grid;" in mobile_input_row_block
    assert (
        'grid-template-areas:\n      "references references"\n      "attachments attachments"\n      "input actions";'
        in mobile_input_row_block
    )
    assert "column-gap: 7px;" in mobile_input_row_block
    assert "row-gap: 0;" in mobile_input_row_block
    assert "flex-basis: 0;" in hidden_block
    assert "width: 0;" in hidden_block
    assert "max-width: 0;" in hidden_block
    attachment_block = css.split(".runtime-chat-attachment {", 1)[1].split(
        ".runtime-chat-attachment:hover",
        1,
    )[0]
    assert "flex: 0 0 var(--chat-attachment-card-width);" in attachment_block
    assert "max-width: var(--chat-attachment-card-width);" in attachment_block
    assert "grid-template-columns: minmax(24px, 1fr);" in compressed_block
    assert "width: 100%;" in compressed_preview_block
    assert "height: 38px;" in compressed_preview_block
    assert "width: 22px;" in compressed_remove_block
    assert "height: 22px;" in compressed_remove_block
    assert "font-weight: 700;" in compressed_remove_block
    assert ".runtime-chat-attachment-preview.is-missing-thumb::before" in css
    assert "grid-area: attachments;" in responsive_attachments
    assert "width: 100%;" in responsive_attachments
    assert "max-width: 100%;" in responsive_attachments
    assert ".runtime-chat-attachment-thumb" in css
    assert ".runtime-chat-attachment-preview" in css
    assert ".runtime-chat-attachment-remove" in css
    assert "runtime.attach_file" in i18n
    assert "runtime.attachment_added" in i18n
    assert "body instanceof FormData" in api_source
    assert "!isNativeBody" in api_source


def test_webchat_layout_keeps_input_at_bottom_and_log_scrollable() -> None:
    app_css = APP_CSS.read_text(encoding="utf-8")
    responsive_css = RESPONSIVE_CSS.read_text(encoding="utf-8")
    main_js = MAIN_JS.read_text(encoding="utf-8")
    template = Path("src/Undefined/webui/templates/index.html").read_text(
        encoding="utf-8"
    )

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
    assert "grid-template-rows: auto auto minmax(0, 1fr) auto;" in chat_card_block
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

    chat_header_block = app_css.split(".runtime-chat-header {", 1)[1].split(
        ".runtime-chat-title", 1
    )[0]
    title_meta_block = app_css.split(".runtime-chat-title-meta", 1)[1].split(
        ".main-content.chat-layout #tab-chat .chat-runtime-card", 1
    )[0]
    mobile_header_block = responsive_css.split(".runtime-chat-header-actions", 1)[
        1
    ].split(".runtime-chat-auto-scroll-toggle", 1)[0]

    assert "align-items: center;" in chat_header_block
    assert "white-space: nowrap;" in title_meta_block
    assert "justify-content: space-between;" in mobile_header_block
    assert ".main-content.chat-layout" in responsive_css
    assert "height: 100dvh;" in responsive_css
    assert "function syncMainContentLayout()" in main_js
    assert (
        'appContent.style.display = state.tab === "chat" ? "grid" : "block";' in main_js
    )
    assert 'role="log"' in template
    assert 'aria-live="polite"' in template
    assert 'data-i18n-aria-label="runtime.chat_log_label"' in template
    assert 'class="header runtime-chat-header"' in template
    assert "runtime-chat-title-meta" in template
    assert "该会话由 WebUI 发起" in template


def test_webchat_mobile_tool_rows_have_overflow_guards() -> None:
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    responsive_css = RESPONSIVE_CSS.read_text(encoding="utf-8")

    status_css = css.split(".runtime-tool-block summary .runtime-tool-status", 1)[
        1
    ].split(".runtime-tool-block summary .runtime-tool-kind", 1)[0]
    kind_css = css.split(".runtime-tool-block summary .runtime-tool-kind", 1)[1].split(
        ".runtime-tool-block.webchat-private-send", 1
    )[0]
    structured_css = css.split(".runtime-tool-structured-row", 1)[1].split(
        ".runtime-tool-key", 1
    )[0]

    assert "min-width: 0;" in status_css
    assert "text-overflow: ellipsis;" in status_css
    assert "overflow: hidden;" in kind_css
    assert "grid-template-columns: minmax(64px, min(34%, 180px))" in structured_css
    assert ".runtime-tool-block summary .runtime-tool-duration" in responsive_css


def test_webchat_content_wraps_long_code_and_markdown_without_horizontal_scroll() -> (
    None
):
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    responsive_css = RESPONSIVE_CSS.read_text(encoding="utf-8")

    log_css = css.split(".runtime-chat-log {", 1)[1].split(
        ".runtime-chat-load-more",
        1,
    )[0]
    item_css = css.split(".runtime-chat-item {", 1)[1].split(
        ".runtime-chat-item.user",
        1,
    )[0]
    code_block_css = css.split(".runtime-code-block {", 1)[1].split(
        ".runtime-code-toolbar",
        1,
    )[0]
    inline_code_css = css.split(".runtime-chat-content code {", 1)[1].split(
        ".runtime-chat-image",
        1,
    )[0]
    mobile_table_css = responsive_css.split(
        ".runtime-chat-content.markdown table",
        1,
    )[1].split(".runtime-chat-input-row", 1)[0]

    assert "min-width: 0;" in log_css
    assert "overflow-x: hidden;" in log_css
    assert "min-width: 0;" in item_css
    assert "max-width: 100%;" in item_css
    assert "min-width: 0;" in code_block_css
    assert "max-width: 100%;" in code_block_css
    assert "white-space: normal;" in inline_code_css
    assert "overflow-wrap: anywhere;" in inline_code_css
    assert "display: table;" in mobile_table_css
    assert "overflow-x: visible;" in mobile_table_css
    assert "white-space: normal;" in mobile_table_css
    mobile_code_toolbar_css = responsive_css.split(".runtime-code-toolbar", 1)[1].split(
        ".runtime-code-actions", 1
    )[0]
    mobile_code_action_css = responsive_css.split(".runtime-code-action", 1)[1].split(
        ".runtime-chat-input-row",
        1,
    )[0]
    assert "min-height: 32px;" in mobile_code_toolbar_css
    assert "padding: 4px 6px 4px 9px;" in mobile_code_toolbar_css
    assert "min-height: 24px;" in mobile_code_action_css
    assert "font-size: 11px;" in mobile_code_action_css
    assert ".runtime-tool-block summary .runtime-tool-kind" in responsive_css
    assert "display: none;" in responsive_css
    assert "max-width: 30vw;" in responsive_css
