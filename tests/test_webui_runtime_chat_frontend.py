"""WebUI / Chat 前端静态契约测试（历史遗留，勿继续扩张）。

本文件大量使用「读取源码文本 + assert 子串」的写法，属于变更检测器：
重构必然变红，真正的行为回归却测不出来（全仓 ~800 处此类断言里本文件占 500+，
由 ``tests/test_source_assertion_budget.py`` 的预算棘轮看住总量，只减不增）。

新增前端契约时请写行为断言：

- 用 node + ``vm`` 执行真实 JS（参考 ``tests/test_webui_config_form_frontend.py``）；
- 原生 App 的断言迁移到各自 App 的 Vitest / cargo 测试；
- 结构化资源（JSON/TOML）断言解析后的字段而非原文子串。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Final

from Undefined.utils import io as async_io


RUNTIME_JS: Final[Path] = Path("src/Undefined/webui/static/js/runtime.js")
RUNTIME_CSS: Final[Path] = Path("src/Undefined/webui/static/css/components.css")
WEBUI_TEMPLATE: Final[Path] = Path("src/Undefined/webui/templates/index.html")
MAIN_JS: Final[Path] = Path("src/Undefined/webui/static/js/main.js")
API_JS: Final[Path] = Path("src/Undefined/webui/static/js/api.js")
LOG_VIEW_JS: Final[Path] = Path("src/Undefined/webui/static/js/log-view.js")
APP_CSS: Final[Path] = Path("src/Undefined/webui/static/css/app.css")
RESPONSIVE_CSS: Final[Path] = Path("src/Undefined/webui/static/css/responsive.css")
I18N_JS: Final[Path] = Path("src/Undefined/webui/static/js/i18n.js")
WEBUI_APP_PY: Final[Path] = Path("src/Undefined/webui/app.py")
TAURI_CONF: Final[Path] = Path("apps/undefined-console/src-tauri/tauri.conf.json")


def _read_source(path: Path) -> str:
    text = asyncio.run(async_io.read_text(path))
    assert text is not None
    return text


def test_webchat_html_preview_csp_allows_inline_scripts_without_eval() -> None:
    webui_app = _read_source(WEBUI_APP_PY)
    tauri_conf = _read_source(TAURI_CONF)

    assert "\"script-src 'self' 'nonce-{nonce}'; \"" in webui_app
    assert "script-src 'self';" in tauri_conf
    assert "script-src 'self' 'unsafe-inline'" not in webui_app
    assert "script-src 'self' 'unsafe-inline'" not in tauri_conf
    assert "__CSP_NONCE__" in _read_source(WEBUI_TEMPLATE)
    assert "htmlRunnerCspMeta" in _read_source(RUNTIME_JS)
    assert "unsafe-eval" not in webui_app
    assert "unsafe-eval" not in tauri_conf


def test_webchat_frontend_has_conversation_sidebar() -> None:
    source = _read_source(RUNTIME_JS)
    template = _read_source(WEBUI_TEMPLATE)
    app_css = _read_source(APP_CSS)
    responsive_css = _read_source(RESPONSIVE_CSS)
    i18n = _read_source(I18N_JS)

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
    source = _read_source(RUNTIME_JS)
    template = _read_source(WEBUI_TEMPLATE)
    css = _read_source(RUNTIME_CSS)
    responsive_css = _read_source(RESPONSIVE_CSS)
    i18n = _read_source(I18N_JS)

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
    assert "commandMatchesForQuery(context.commandQuery)" in source
    assert "function chatCommandDisplayName" in source
    assert "typedCommandName: chatCommandDisplayName(" in source
    assert "const commandName = match.typedCommandName || match.command.name" in source
    assert (
        "if (!command) {\n                return commandMatchesForQuery(context.commandQuery);"
        in source
    )
    assert "function renderChatCommandNoSubcommandsHelp" in source
    assert "function chatCommandPaletteEmptyHtml" in source
    assert "commandTextWithTypedTrigger" in source
    assert "commandAliasText" in source
    assert "!runtimeState.chatCommandsLoaded" in source
    assert "runtime.chat_command_loading" in source
    assert "runtime.chat_command_unknown_command" in source
    assert "runtime.chat_command_subcommand_empty" in source
    assert "runtime.command_no_subcommands_note" in source
    assert "runtime.command_usage" in source
    assert "runtime.command_example" in source
    assert "runtime.command_aliases" in source
    assert "runtime-chat-command-help" in source
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
    assert "runtime.chat_command_loading" in i18n
    assert "runtime.chat_command_empty" in i18n
    assert "runtime.chat_command_unknown_command" in i18n
    assert "runtime.chat_command_subcommand_empty" in i18n
    assert "runtime.chat_command_subcommands" in i18n
    assert "runtime.command_help" in i18n
    assert "runtime.command_usage" in i18n
    assert "runtime.command_example" in i18n
    assert "runtime.command_aliases" in i18n
    assert "runtime.command_no_subcommands_note" in i18n


def test_webchat_frontend_resumes_backend_job_after_refresh_or_reconnect() -> None:
    source = _read_source(RUNTIME_JS)
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
    source = _read_source(RUNTIME_JS)
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


def test_webui_logs_fetch_more_tail_lines_by_default() -> None:
    source = _read_source(LOG_VIEW_JS)

    assert "const LOG_TAIL_LINES = 5000;" in source
    assert 'lines: "200"' not in source
    assert "lines: String(LOG_TAIL_LINES)" in source


def test_webchat_tool_snapshots_do_not_rerender_unchanged_blocks() -> None:
    source = _read_source(RUNTIME_JS)
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


def test_webchat_frontend_polls_job_events_incrementally() -> None:
    source = _read_source(RUNTIME_JS)

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
    source = _read_source(RUNTIME_JS)
    resume_helper = source.split("async function resumeActiveChatJob", 1)[1].split(
        "async function clearChatHistory", 1
    )[0]

    assert "activeJobResumeTimer" in source
    assert "ACTIVE_JOB_RESUME_MAX_ATTEMPTS = 20" in source
    assert "runtimeState.activeJobResumeAttempts += 1" in resume_helper
    assert "setTimeout(() => {" in resume_helper
    assert "resumeActiveChatJob().catch" in resume_helper
    assert 'window.addEventListener(\n                "online"' in source


def test_webchat_tool_blocks_auto_collapse_after_minimum_visible_time() -> None:
    source = _read_source(RUNTIME_JS)
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


def test_webchat_tab_activation_forces_bottom_scroll_after_history_load() -> None:
    source = _read_source(RUNTIME_JS)
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


def test_webchat_frontend_has_clickable_image_viewer() -> None:
    source = _read_source(RUNTIME_JS)
    template = _read_source(WEBUI_TEMPLATE)
    css = _read_source(RUNTIME_CSS)
    responsive_css = _read_source(RESPONSIVE_CSS)
    i18n = _read_source(I18N_JS)

    assert 'id="runtimeChatImageViewer"' in template
    assert 'id="runtimeChatImageViewerImage"' in template
    assert "data-chat-image-viewer-close" in template
    assert "function chatImageMarkup" in source
    assert 'data-chat-image-preview="1"' in source
    assert "function openChatImageViewer" in source
    assert "function closeChatImageViewer" in source
    assert "runtimeState.imageViewerPreviousFocus" in source
    assert '".runtime-chat-image[data-chat-image-preview]"' in source
    assert 'event.key === "Escape"' in source
    assert 'target.closest(".runtime-chat-image-viewer-figure")' in source
    assert "runtime.open_image_preview" in i18n
    assert "runtime.image_preview" in i18n
    assert ".runtime-chat-image-viewer" in css
    assert ".runtime-chat-image-viewer.is-open" in css
    assert ".runtime-chat-image-viewer-close" in css
    assert "cursor: zoom-in;" in css
    assert "@keyframes runtime-chat-image-viewer-in" in css
    assert ".runtime-chat-image-viewer" in responsive_css


def test_webchat_html_runner_runs_code_in_sandboxed_preview() -> None:
    source = _read_source(RUNTIME_JS)
    css = _read_source(RUNTIME_CSS)
    responsive_css = _read_source(RESPONSIVE_CSS)
    template = _read_source(WEBUI_TEMPLATE)
    i18n = _read_source(I18N_JS)

    assert 'id="runtimeHtmlRunner"' in template
    assert 'id="runtimeHtmlRunnerFrame"' in template
    assert 'sandbox="allow-scripts"' in template
    assert "allow-forms" not in template
    assert "allow-modals" not in template
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
    assert "function injectHtmlRunnerSecurity" in source
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
    assert "frame.srcdoc = injectHtmlRunnerSecurity(html)" in source
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
    source = _read_source(RUNTIME_JS)
    css = _read_source(RUNTIME_CSS)
    responsive_css = _read_source(RESPONSIVE_CSS)
    template = _read_source(WEBUI_TEMPLATE)
    i18n = _read_source(I18N_JS)

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
    assert "const outboundAttachments = retryMessage ? [] : attachments" in send_helper
    assert "const outboundReferences = retryMessage ? [] : references" in send_helper
    assert (
        "!message &&\n            !outboundAttachments.length &&\n            !outboundReferences.length"
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
    css = _read_source(RUNTIME_CSS)
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
    source = _read_source(RUNTIME_JS)
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
    assert (
        'if (!retryMessage) {\n                appendChatMessage("user", outboundMessage);\n            }'
        in send_helper
    )
    assert 'input.value = ""' in send_helper
    assert "clearChatAttachments()" in send_helper
    assert "forceScrollChatToBottomSoon()" in send_helper
    assert "ensureStreamingMessage()" in send_helper


def test_webchat_frontend_pastes_files_as_pending_attachments() -> None:
    source = _read_source(RUNTIME_JS)
    css = _read_source(RUNTIME_CSS)
    template = _read_source(WEBUI_TEMPLATE)
    i18n = _read_source(I18N_JS)
    api_source = _read_source(API_JS)

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
        _read_source(RESPONSIVE_CSS)
        .split(
            ".runtime-chat-attachments",
            1,
        )[1]
        .split(".runtime-chat-attachment", 1)[0]
    )
    mobile_input_row_block = (
        _read_source(RESPONSIVE_CSS)
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
    app_css = _read_source(APP_CSS)
    responsive_css = _read_source(RESPONSIVE_CSS)
    main_js = _read_source(MAIN_JS)
    template = _read_source(WEBUI_TEMPLATE)

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
    layout_block = main_js.split("function syncMainContentLayout()", 1)[1].split(
        "\n}\n", 1
    )[0]
    assert 'state.tab === "chat" || state.tab === "schedules"' in layout_block
    assert 'appContent.style.display = "grid";' in layout_block
    assert 'appContent.style.display = "block";' in layout_block
    assert 'appContent.style.display = "none";' in layout_block
    assert 'role="log"' in template
    assert 'aria-live="polite"' in template
    assert 'data-i18n-aria-label="runtime.chat_log_label"' in template
    assert 'class="header runtime-chat-header"' in template
    assert "runtime-chat-title-meta" in template
    assert "该会话由 WebUI 发起" in template


def test_webchat_mobile_tool_rows_have_overflow_guards() -> None:
    css = _read_source(RUNTIME_CSS)
    responsive_css = _read_source(RESPONSIVE_CSS)

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
    css = _read_source(RUNTIME_CSS)
    responsive_css = _read_source(RESPONSIVE_CSS)

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
