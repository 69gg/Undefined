"""MessageHandler 复读功能测试"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.handlers import (
    MessageHandler,
    REPEAT_REPLY_HISTORY_PREFIX,
)


def _build_handler(
    *,
    repeat_enabled: bool = False,
    repeat_threshold: int = 3,
    inverted_question_enabled: bool = False,
    keyword_reply_enabled: bool = False,
) -> Any:
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        bot_qq=10000,
        repeat_enabled=repeat_enabled,
        repeat_threshold=repeat_threshold,
        inverted_question_enabled=inverted_question_enabled,
        keyword_reply_enabled=keyword_reply_enabled,
        bilibili_auto_extract_enabled=False,
        arxiv_auto_extract_enabled=False,
        should_process_group_message=lambda is_at_bot=False: True,
        should_process_private_message=lambda: True,
        is_group_allowed=lambda _gid: True,
        is_private_allowed=lambda _uid: True,
        access_control_enabled=lambda: False,
        process_every_message=True,
    )
    handler.history_manager = SimpleNamespace(
        add_group_message=AsyncMock(),
        add_private_message=AsyncMock(),
    )
    handler.sender = SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(),
    )
    handler.ai_coordinator = SimpleNamespace(
        handle_auto_reply=AsyncMock(),
        handle_private_reply=AsyncMock(),
        _is_at_bot=lambda _mc: False,
    )
    handler.ai = SimpleNamespace(
        _cognitive_service=None,
        memory_storage=None,
        model_pool=SimpleNamespace(
            handle_private_message=AsyncMock(return_value=False)
        ),
    )
    handler.onebot = SimpleNamespace(
        get_group_info=AsyncMock(return_value={"group_name": "测试群"}),
        get_stranger_info=AsyncMock(return_value={"nickname": "用户"}),
        get_msg=AsyncMock(return_value=None),
        get_forward_msg=AsyncMock(return_value=None),
    )
    handler.command_dispatcher = SimpleNamespace(
        parse_command=lambda _t: None,
    )
    handler._background_tasks = set()
    handler._repeat_counter = {}
    handler._repeat_locks = {}
    handler._profile_name_refresh_cache = {}
    return handler


def _group_event(
    group_id: int = 30001,
    sender_id: int = 20001,
    text: str = "hello",
) -> dict[str, Any]:
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": group_id,
        "user_id": sender_id,
        "message_id": 1,
        "sender": {
            "user_id": sender_id,
            "card": f"用户{sender_id}",
            "nickname": f"昵称{sender_id}",
            "role": "member",
            "title": "",
        },
        "message": [{"type": "text", "data": {"text": text}}],
    }


# ── 基础：复读未启用时不触发 ──


@pytest.mark.asyncio
async def test_repeat_disabled_does_not_repeat() -> None:
    handler = _build_handler(repeat_enabled=False)
    for uid in [20001, 20002, 20003]:
        await handler.handle_message(_group_event(sender_id=uid, text="hello"))

    handler.sender.send_group_message.assert_not_called()


# ── 复读触发：3条相同消息来自不同人 ──


@pytest.mark.asyncio
async def test_repeat_triggers_on_3_identical_from_different_senders() -> None:
    handler = _build_handler(repeat_enabled=True)
    for uid in [20001, 20002, 20003]:
        await handler.handle_message(_group_event(sender_id=uid, text="hello"))

    handler.sender.send_group_message.assert_called_once()
    call = handler.sender.send_group_message.call_args
    assert call.args[0] == 30001
    assert call.args[1] == "hello"
    assert call.kwargs.get("history_prefix") == REPEAT_REPLY_HISTORY_PREFIX


# ── 不触发：3条相同消息来自同一人 ──


@pytest.mark.asyncio
async def test_repeat_does_not_trigger_from_same_sender() -> None:
    handler = _build_handler(repeat_enabled=True)
    for _ in range(3):
        await handler.handle_message(_group_event(sender_id=20001, text="hello"))

    handler.sender.send_group_message.assert_not_called()


# ── 不触发：消息内容不同 ──


@pytest.mark.asyncio
async def test_repeat_does_not_trigger_for_different_texts() -> None:
    handler = _build_handler(repeat_enabled=True)
    for uid, text in [(20001, "hello"), (20002, "world"), (20003, "hello")]:
        await handler.handle_message(_group_event(sender_id=uid, text=text))

    handler.sender.send_group_message.assert_not_called()


# ── 防重复：触发后计数器清空 ──


@pytest.mark.asyncio
async def test_repeat_clears_counter_after_trigger() -> None:
    handler = _build_handler(repeat_enabled=True)
    # 第一轮：3条相同触发复读
    for uid in [20001, 20002, 20003]:
        await handler.handle_message(_group_event(sender_id=uid, text="hello"))

    assert handler.sender.send_group_message.call_count == 1

    # 第二轮：再来3条相同应再次触发
    for uid in [20004, 20005, 20006]:
        await handler.handle_message(_group_event(sender_id=uid, text="hello"))

    assert handler.sender.send_group_message.call_count == 2


# ── 倒问号：问号消息触发倒问号 ──


@pytest.mark.asyncio
async def test_inverted_question_sends_inverted_mark() -> None:
    handler = _build_handler(repeat_enabled=True, inverted_question_enabled=True)
    for uid in [20001, 20002, 20003]:
        await handler.handle_message(_group_event(sender_id=uid, text="?"))

    handler.sender.send_group_message.assert_called_once()
    call = handler.sender.send_group_message.call_args
    assert call.args[1] == "¿"


@pytest.mark.asyncio
async def test_inverted_question_multiple_marks() -> None:
    handler = _build_handler(repeat_enabled=True, inverted_question_enabled=True)
    for uid in [20001, 20002, 20003]:
        await handler.handle_message(_group_event(sender_id=uid, text="???"))

    handler.sender.send_group_message.assert_called_once()
    call = handler.sender.send_group_message.call_args
    assert call.args[1] == "¿¿¿"


@pytest.mark.asyncio
async def test_inverted_question_chinese_question_mark() -> None:
    handler = _build_handler(repeat_enabled=True, inverted_question_enabled=True)
    for uid in [20001, 20002, 20003]:
        await handler.handle_message(_group_event(sender_id=uid, text="？"))

    handler.sender.send_group_message.assert_called_once()
    call = handler.sender.send_group_message.call_args
    assert call.args[1] == "¿"


@pytest.mark.asyncio
async def test_inverted_question_disabled_sends_normal_text() -> None:
    handler = _build_handler(repeat_enabled=True, inverted_question_enabled=False)
    for uid in [20001, 20002, 20003]:
        await handler.handle_message(_group_event(sender_id=uid, text="?"))

    handler.sender.send_group_message.assert_called_once()
    call = handler.sender.send_group_message.call_args
    assert call.args[1] == "?"


@pytest.mark.asyncio
async def test_inverted_question_mixed_text_not_triggered() -> None:
    """非纯问号消息不受倒问号影响，正常复读。"""
    handler = _build_handler(repeat_enabled=True, inverted_question_enabled=True)
    for uid in [20001, 20002, 20003]:
        await handler.handle_message(_group_event(sender_id=uid, text="what?"))

    handler.sender.send_group_message.assert_called_once()
    call = handler.sender.send_group_message.call_args
    assert call.args[1] == "what?"


# ── 不同群互不干扰 ──


@pytest.mark.asyncio
async def test_repeat_groups_are_independent() -> None:
    handler = _build_handler(repeat_enabled=True)
    # 群A: 2条相同
    await handler.handle_message(
        _group_event(group_id=30001, sender_id=20001, text="hi")
    )
    await handler.handle_message(
        _group_event(group_id=30001, sender_id=20002, text="hi")
    )
    # 群B: 3条相同
    for uid in [30001, 30002, 30003]:
        await handler.handle_message(
            _group_event(group_id=30002, sender_id=uid, text="hi")
        )

    # 群B触发，群A未触发
    assert handler.sender.send_group_message.call_count == 1
    call = handler.sender.send_group_message.call_args
    assert call.args[0] == 30002


# ── 计数器窗口：只看最近 N 条 ──


@pytest.mark.asyncio
async def test_repeat_counter_sliding_window() -> None:
    handler = _build_handler(repeat_enabled=True)
    # 发5条不同消息
    for i in range(5):
        await handler.handle_message(_group_event(sender_id=20001 + i, text=f"msg{i}"))
    # 再发3条相同
    for uid in [20010, 20011, 20012]:
        await handler.handle_message(_group_event(sender_id=uid, text="hello"))

    handler.sender.send_group_message.assert_called_once()
    call = handler.sender.send_group_message.call_args
    assert call.args[1] == "hello"


# ── bot 自身发言后不触发复读 ──

BOT_QQ = 10000


@pytest.mark.asyncio
async def test_repeat_no_trigger_when_bot_sends_before_users() -> None:
    """bot 先发，后面用户再发相同消息，不应触发复读。"""
    handler = _build_handler(repeat_enabled=True)
    # bot 先发
    await handler.handle_message(_group_event(sender_id=BOT_QQ, text="hello"))
    # 两个用户跟发
    for uid in [20001, 20002]:
        await handler.handle_message(_group_event(sender_id=uid, text="hello"))

    handler.sender.send_group_message.assert_not_called()


@pytest.mark.asyncio
async def test_repeat_no_trigger_when_bot_sends_in_middle() -> None:
    """用户发到一半，bot 插入相同消息，之后用户再凑满阈值，不应触发复读。"""
    handler = _build_handler(repeat_enabled=True)
    # 两个用户先发
    await handler.handle_message(_group_event(sender_id=20001, text="hello"))
    await handler.handle_message(_group_event(sender_id=20002, text="hello"))
    # bot 插入
    await handler.handle_message(_group_event(sender_id=BOT_QQ, text="hello"))
    # 第三个用户发：此时窗口 [user2, bot, user3]，含 bot → 不触发
    await handler.handle_message(_group_event(sender_id=20003, text="hello"))

    handler.sender.send_group_message.assert_not_called()


@pytest.mark.asyncio
async def test_repeat_triggers_after_bot_window_slides_out() -> None:
    """bot 消息滑出窗口后，纯用户序列应正常触发复读（threshold=3）。"""
    handler = _build_handler(repeat_enabled=True, repeat_threshold=3)
    # bot 先发（进入窗口）
    await handler.handle_message(_group_event(sender_id=BOT_QQ, text="hello"))
    # 三个不同用户依次发：窗口变为 [user1, user2, user3]（bot 已滑出）
    for uid in [20001, 20002, 20003]:
        await handler.handle_message(_group_event(sender_id=uid, text="hello"))

    handler.sender.send_group_message.assert_called_once()
    assert handler.sender.send_group_message.call_args.args[1] == "hello"


# ── 可配置阈值 ──


@pytest.mark.asyncio
async def test_repeat_custom_threshold_2() -> None:
    """threshold=2 时，2 条不同发送者相同消息即触发复读。"""
    handler = _build_handler(repeat_enabled=True, repeat_threshold=2)
    for uid in [20001, 20002]:
        await handler.handle_message(_group_event(sender_id=uid, text="hi"))

    handler.sender.send_group_message.assert_called_once()
    assert handler.sender.send_group_message.call_args.args[1] == "hi"


@pytest.mark.asyncio
async def test_repeat_custom_threshold_4() -> None:
    """threshold=4 时，3 条不同发送者相同消息不触发，第 4 条才触发。"""
    handler = _build_handler(repeat_enabled=True, repeat_threshold=4)
    for uid in [20001, 20002, 20003]:
        await handler.handle_message(_group_event(sender_id=uid, text="hey"))
    handler.sender.send_group_message.assert_not_called()

    await handler.handle_message(_group_event(sender_id=20004, text="hey"))
    handler.sender.send_group_message.assert_called_once()
    assert handler.sender.send_group_message.call_args.args[1] == "hey"
