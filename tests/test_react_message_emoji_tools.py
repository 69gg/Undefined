from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.skills.toolsets.messages.list_emojis.handler import (
    execute as list_emojis_execute,
)
from Undefined.skills.toolsets.messages.lookup_emoji_id.handler import (
    execute as lookup_emoji_id_execute,
)
from Undefined.skills.toolsets.messages.react_message_emoji.handler import (
    execute as react_message_emoji_execute,
)
from Undefined.utils.message_turn import mark_message_sent_this_turn


def _runtime_config() -> Any:
    return SimpleNamespace(
        is_group_allowed=lambda _gid: True,
        is_private_allowed=lambda _uid: True,
    )


def _tool_context(**values: Any) -> dict[str, Any]:
    return {"mark_message_sent_this_turn": mark_message_sent_this_turn, **values}


@pytest.mark.asyncio
async def test_react_message_emoji_uses_trigger_message_id_and_alias() -> None:
    onebot_client = SimpleNamespace(
        get_msg=AsyncMock(return_value={"message_type": "group", "group_id": 1001}),
        fetch_emoji_like=AsyncMock(return_value={"emoji_likes": []}),
        set_msg_emoji_like=AsyncMock(return_value={}),
    )
    context: dict[str, Any] = _tool_context(
        request_type="group",
        group_id=1001,
        sender_id=2002,
        request_id="req-react-1",
        trigger_message_id=5555,
        runtime_config=_runtime_config(),
        onebot_client=onebot_client,
    )

    result = await react_message_emoji_execute({"emoji": "👍"}, context)

    assert result == "已为消息 5555 添加表情（emoji_id=76）"
    onebot_client.set_msg_emoji_like.assert_called_once_with(5555, 76, set_like=True)
    assert context["message_sent_this_turn"] is True


@pytest.mark.asyncio
async def test_react_message_emoji_skip_when_already_set() -> None:
    onebot_client = SimpleNamespace(
        get_msg=AsyncMock(return_value={"message_type": "group", "group_id": 1001}),
        fetch_emoji_like=AsyncMock(
            return_value={"emoji_likes": [{"emoji_id": 76, "is_liked": True}]}
        ),
        set_msg_emoji_like=AsyncMock(return_value={}),
    )
    context: dict[str, Any] = _tool_context(
        request_type="group",
        group_id=1001,
        request_id="req-react-2",
        trigger_message_id=6666,
        runtime_config=_runtime_config(),
        onebot_client=onebot_client,
    )

    result = await react_message_emoji_execute({"emoji_id": 76}, context)

    assert result == "消息 6666 已有 emoji_id=76，无需重复添加"
    onebot_client.set_msg_emoji_like.assert_not_called()


@pytest.mark.asyncio
async def test_react_message_emoji_reject_cross_session_by_default() -> None:
    onebot_client = SimpleNamespace(
        get_msg=AsyncMock(return_value={"message_type": "group", "group_id": 9999}),
        fetch_emoji_like=AsyncMock(return_value={}),
        set_msg_emoji_like=AsyncMock(return_value={}),
    )
    context: dict[str, Any] = _tool_context(
        request_type="group",
        group_id=1001,
        request_id="req-react-3",
        trigger_message_id=7777,
        runtime_config=_runtime_config(),
        onebot_client=onebot_client,
    )

    result = await react_message_emoji_execute({"emoji_id": 76}, context)

    assert "目标消息不属于当前会话" in result
    onebot_client.set_msg_emoji_like.assert_not_called()


@pytest.mark.asyncio
async def test_react_message_emoji_dedup_parallel_same_operation() -> None:
    async def delayed_set(*args: Any, **kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return {}

    onebot_client = SimpleNamespace(
        get_msg=AsyncMock(return_value={"message_type": "group", "group_id": 1001}),
        fetch_emoji_like=AsyncMock(return_value={"emoji_likes": []}),
        set_msg_emoji_like=AsyncMock(side_effect=delayed_set),
    )
    context: dict[str, Any] = _tool_context(
        request_type="group",
        group_id=1001,
        request_id="req-react-4",
        trigger_message_id=8888,
        runtime_config=_runtime_config(),
        onebot_client=onebot_client,
    )

    result_1, result_2 = await asyncio.gather(
        react_message_emoji_execute({"emoji_id": 76}, context),
        react_message_emoji_execute({"emoji_id": 76}, context),
    )

    assert onebot_client.set_msg_emoji_like.call_count == 1
    assert sorted([result_1, result_2]) == sorted(
        [
            "已为消息 8888 添加表情（emoji_id=76）",
            "已跳过重复操作：消息 8888 的 emoji_id=76 已处理 action=set",
        ]
    )


@pytest.mark.asyncio
async def test_lookup_and_list_emoji_tools() -> None:
    lookup = await lookup_emoji_id_execute({"emoji": "点赞"}, {})
    listed = await list_emojis_execute({"keyword": "点赞", "limit": 5}, {})

    assert "emoji_id=76" in lookup
    assert "76" in listed
