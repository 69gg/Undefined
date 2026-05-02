from __future__ import annotations

from Undefined.ai.client import (
    _INVALID_TOOL_CALL_CONTENT,
    _build_invalid_tool_call_response,
)


def test_build_invalid_tool_call_response_keeps_call_id() -> None:
    response = _build_invalid_tool_call_response(
        {"id": "call_empty", "function": {"name": "", "arguments": "{}"}}
    )

    assert response == {
        "role": "tool",
        "tool_call_id": "call_empty",
        "name": "",
        "content": _INVALID_TOOL_CALL_CONTENT,
    }


def test_build_invalid_tool_call_response_handles_non_dict() -> None:
    response = _build_invalid_tool_call_response("bad")

    assert response["role"] == "tool"
    assert response["tool_call_id"] == ""
    assert response["name"] == ""
    assert "工具名称为空或格式非法" in str(response["content"])
