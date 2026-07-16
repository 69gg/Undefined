from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator

from Undefined.context import RequestContext
from Undefined.skills.toolsets.messages.send_private_message.handler import execute
from Undefined.utils import io as async_io
from Undefined.utils.coerce import was_message_sent
from Undefined.utils.message_targets import (
    parse_delivery_address,
    resolve_delivery_address,
)
from Undefined.utils.message_turn import mark_message_sent_this_turn


def _build_runtime_config() -> Any:
    return SimpleNamespace(
        is_private_allowed=lambda _uid: True,
    )


def _tool_context(**values: Any) -> dict[str, Any]:
    return {
        "mark_message_sent_this_turn": mark_message_sent_this_turn,
        "parse_delivery_address": parse_delivery_address,
        "resolve_delivery_address": resolve_delivery_address,
        **values,
    }


@pytest.mark.asyncio
async def test_send_private_message_schema_describes_wechat_text_format() -> None:
    config_text = await async_io.read_text(
        Path("src/Undefined/skills/toolsets/messages/send_private_message/config.json")
    )
    assert config_text is not None
    function = json.loads(config_text)["function"]
    parameters = function["parameters"]
    validator = Draft202012Validator(parameters)

    assert "微信文本支持 Markdown" in function["description"]
    assert "特殊符号和附件标签必须原样填写" in function["description"]
    assert "message 参数是 JSON 字符串而不是 XML/HTML" in function["description"]
    assert "错误的 &it;" in function["description"]
    assert (
        "message 是 JSON 字符串，不需要 XML/HTML 转义"
        in function["parameters"]["properties"]["message"]["description"]
    )
    assert (
        "发送前检查并消除 &lt;"
        in function["parameters"]["properties"]["message"]["description"]
    )
    assert "同一物理会话内的 reply_to 原生引用" in function["description"]
    assert validator.is_valid(
        {
            "message": "hello",
            "address": "wechat:12345",
            "reply_to": "wechat-message+/=1",
        }
    )
    assert not validator.is_valid(
        {
            "message": "hello",
            "address": "wechat:12345",
            "reply_to": "invalid message id",
        }
    )


@pytest.mark.asyncio
async def test_send_private_message_callback_passes_reply_to() -> None:
    send_private_message_callback = AsyncMock()
    context: dict[str, Any] = _tool_context(
        user_id=12345,
        request_id="req-private-1",
        runtime_config=_build_runtime_config(),
        send_private_message_callback=send_private_message_callback,
    )

    result = await execute(
        {
            "message": "hello direct private",
            "reply_to": 88888,
        },
        context,
    )

    assert result == "私聊消息已发送给用户 12345"
    send_private_message_callback.assert_awaited_once_with(
        12345, "hello direct private", reply_to=88888
    )
    assert context["message_sent_this_turn"] is True


@pytest.mark.asyncio
async def test_send_private_message_wechat_passes_string_reply_id() -> None:
    sender = SimpleNamespace(
        send_address_message=AsyncMock(return_value="client-message-1"),
    )
    context: dict[str, Any] = _tool_context(
        user_id=12345,
        channel="wechat",
        address="wechat:12345",
        request_id="req-private-wechat-reply",
        runtime_config=_build_runtime_config(),
        sender=sender,
    )

    result = await execute(
        {
            "message": "微信引用回复",
            "reply_to": "wechat-message+/=1",
        },
        context,
    )

    assert result == "私聊消息已发送给用户 12345（message_id=client-message-1）"
    sender.send_address_message.assert_awaited_once()
    send_call = sender.send_address_message.await_args
    assert send_call is not None
    assert send_call.args[0].canonical == "wechat:12345"
    assert send_call.args[1] == "微信引用回复"
    assert send_call.kwargs["reply_to"] == "wechat-message+/=1"


@pytest.mark.asyncio
async def test_send_private_message_marks_request_context_when_context_is_copied() -> (
    None
):
    send_private_message_callback = AsyncMock()
    context: dict[str, Any] = _tool_context(
        user_id=12345,
        request_id="req-private-context",
        runtime_config=_build_runtime_config(),
        send_private_message_callback=send_private_message_callback,
    )

    async with RequestContext(request_type="private", user_id=12345) as req_ctx:
        result = await execute({"message": "hello direct private"}, dict(context))

        assert result == "私聊消息已发送给用户 12345"
        assert was_message_sent(req_ctx) is True

    assert "message_sent_this_turn" not in context


@pytest.mark.asyncio
async def test_send_private_message_returns_sent_message_id_when_available() -> None:
    sender = SimpleNamespace(
        send_private_message=AsyncMock(return_value=99999),
    )
    context: dict[str, Any] = _tool_context(
        user_id=12345,
        request_id="req-private-2",
        runtime_config=_build_runtime_config(),
        sender=sender,
    )

    result = await execute(
        {
            "message": "hello sender private",
        },
        context,
    )

    assert result == "私聊消息已发送给用户 12345（message_id=99999）"
    sender.send_private_message.assert_awaited_once_with(
        12345,
        "hello sender private",
        reply_to=None,
        history_message="hello sender private",
    )
