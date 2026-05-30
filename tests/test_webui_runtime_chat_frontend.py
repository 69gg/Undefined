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


def test_webchat_frontend_handles_tool_delta_and_webchat_hints() -> None:
    source = RUNTIME_JS.read_text(encoding="utf-8")

    assert 'event === "tool_delta"' in source
    assert 'payload && Object.hasOwn(payload, "arguments_delta")' in source
    assert 'block.uiHint === "webchat_private_send"' in source
    assert 'block.uiHint === "webchat_end"' in source
    assert 'nextUiHint === "webchat_private_send"' in source
