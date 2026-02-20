from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.context import RequestContext
from Undefined.skills.toolsets.group.get_member_title.handler import execute


@pytest.mark.asyncio
async def test_get_member_title_from_context_group() -> None:
    onebot_client = type("OneBotClientStub", (), {})()
    onebot_client.get_group_member_info = AsyncMock(
        return_value={
            "nickname": "昵称A",
            "card": "群名片A",
            "title": "龙王",
            "title_expire_time": 0,
        }
    )
    context: dict[str, Any] = {
        "group_id": 10001,
        "request_id": "req-1",
        "onebot_client": onebot_client,
    }

    result = await execute({"user_id": 20002}, context)

    onebot_client.get_group_member_info.assert_called_once_with(10001, 20002, False)
    assert "【群头衔】群号: 10001" in result
    assert "成员: 群名片A (QQ: 20002)" in result
    assert "头衔: 龙王" in result
    assert "头衔过期时间: 无" in result


@pytest.mark.asyncio
async def test_get_member_title_uses_request_context_fallback() -> None:
    onebot_client = type("OneBotClientStub", (), {})()
    onebot_client.get_group_member_info = AsyncMock(
        return_value={
            "nickname": "昵称B",
            "card": "",
            "title": "",
            "title_expire_time": -1,
        }
    )
    context: dict[str, Any] = {
        "onebot_client": onebot_client,
    }

    async with RequestContext(
        request_type="group",
        group_id=70007,
        user_id=80008,
        sender_id=80008,
    ):
        result = await execute({"qq": 80008, "no_cache": True}, context)

    onebot_client.get_group_member_info.assert_called_once_with(70007, 80008, True)
    assert "【群头衔】群号: 70007" in result
    assert "成员: 昵称B (QQ: 80008)" in result
    assert "头衔: 无" in result
    assert "头衔过期时间: 永久" in result


@pytest.mark.asyncio
async def test_get_member_title_uses_onebot_from_request_context_resource() -> None:
    onebot_client = type("OneBotClientStub", (), {})()
    onebot_client.get_group_member_info = AsyncMock(
        return_value={
            "nickname": "昵称C",
            "card": "",
            "title": "守护者",
            "title_expire_time": 0,
        }
    )

    async with RequestContext(
        request_type="group",
        group_id=90009,
        user_id=90010,
        sender_id=90010,
    ) as ctx:
        ctx.set_resource("onebot_client", onebot_client)
        result = await execute({"user_id": 90010}, {})

    onebot_client.get_group_member_info.assert_called_once_with(90009, 90010, False)
    assert "【群头衔】群号: 90009" in result
    assert "成员: 昵称C (QQ: 90010)" in result
    assert "头衔: 守护者" in result


@pytest.mark.asyncio
async def test_get_member_title_rejects_conflicting_user_args() -> None:
    onebot_client = type("OneBotClientStub", (), {})()
    onebot_client.get_group_member_info = AsyncMock()
    context: dict[str, Any] = {
        "group_id": 10001,
        "onebot_client": onebot_client,
    }

    result = await execute({"user_id": 20002, "qq": 20003}, context)

    assert result == "参数冲突：user_id 与 qq 不一致"
    onebot_client.get_group_member_info.assert_not_called()
