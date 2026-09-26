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
