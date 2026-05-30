from __future__ import annotations

from pathlib import Path


RUNTIME_JS = Path("src/Undefined/webui/static/js/runtime.js")


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


def test_webchat_frontend_restores_history_tool_blocks_without_stream_state() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")

    assert "function appendHistoryChatItem" in source
    assert "function renderHistoryToolBlocks" in source
    assert "function reduceToolBlock" in source
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


def test_webchat_frontend_places_tools_before_message_content() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")
    attach_helper = source.split("function attachToolBlocks", 1)[1].split(
        "function upsertToolBlock", 1
    )[0]

    assert 'item.querySelector(".runtime-chat-content")' in attach_helper
    assert "item.insertBefore(toolsEl, contentEl)" in attach_helper
