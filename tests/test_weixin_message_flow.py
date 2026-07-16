from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from Undefined.handlers import MessageHandler
from Undefined.utils.message_reply import ReplyContext


def _build_handler(history_record: dict[str, Any] | None) -> Any:
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        model_pool_enabled=False,
        is_private_allowed=lambda _user_id: True,
        should_process_private_message=lambda: True,
    )
    handler.sender = SimpleNamespace()
    handler.history_manager = SimpleNamespace(
        find_private_message_by_id=AsyncMock(return_value=history_record),
        add_private_message=AsyncMock(),
    )
    handler.ai_coordinator = SimpleNamespace(
        handle_private_reply=AsyncMock(),
    )
    handler.command_dispatcher = SimpleNamespace(
        parse_command=MagicMock(return_value=None),
    )
    handler._run_pipelines = AsyncMock()
    handler._schedule_meme_ingest = MagicMock()
    return handler


@pytest.mark.asyncio
async def test_weixin_reply_placeholder_is_restored_from_same_route_history() -> None:
    quoted_attachment = {
        "uid": "pic_quote",
        "kind": "image",
        "media_type": "image",
        "display_name": "quote.png",
    }
    handler = _build_handler(
        {
            "message_id": "quoted-message",
            "display_name": "微信用户1708213363",
            "message": "这是历史中的引用原文 <原样>",
            "attachments": [quoted_attachment],
            "transport": {
                "channel": "wechat",
                "address": "wechat:1708213363",
            },
        }
    )

    await handler.handle_weixin_private_message(
        qq_id=1708213363,
        text="当前消息",
        message_content=[{"type": "text", "data": {"text": "当前消息"}}],
        attachments=[],
        sender_name="微信用户1708213363",
        message_id="current-message",
        account_alias="primary",
        reply_context=ReplyContext(
            title="引用消息",
            message_id="quoted-message",
            text="[消息]",
        ),
    )

    lookup = handler.history_manager.find_private_message_by_id
    lookup.assert_awaited_once_with(
        1708213363,
        "quoted-message",
        channel="wechat",
        address="wechat:1708213363",
    )
    expected = ReplyContext(
        title="微信用户1708213363",
        message_id="quoted-message",
        text="这是历史中的引用原文 <原样>",
        attachments=(quoted_attachment,),
    )
    history_call = handler.history_manager.add_private_message.await_args
    assert history_call is not None
    assert history_call.kwargs["reply_context"] == expected
    ai_call = handler.ai_coordinator.handle_private_reply.await_args
    assert ai_call is not None
    assert ai_call.kwargs["reply_context"] == expected


@pytest.mark.asyncio
async def test_weixin_reply_wire_text_is_not_replaced_from_history() -> None:
    handler = _build_handler(
        {
            "message_id": "quoted-message",
            "message": "不应覆盖上游摘要",
        }
    )
    reply_context = ReplyContext(
        title="微信用户",
        message_id="quoted-message",
        text="上游已经提供的引用正文",
    )

    await handler.handle_weixin_private_message(
        qq_id=1708213363,
        text="当前消息",
        message_content=[],
        attachments=[],
        sender_name="微信用户1708213363",
        message_id="current-message",
        account_alias="primary",
        reply_context=reply_context,
    )

    handler.history_manager.find_private_message_by_id.assert_not_awaited()
    ai_call = handler.ai_coordinator.handle_private_reply.await_args
    assert ai_call is not None
    assert ai_call.kwargs["reply_context"] == reply_context
