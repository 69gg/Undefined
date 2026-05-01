from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from Undefined.skills.toolsets.group_analysis.member_structure.handler import (
    execute as member_structure_execute,
)
from Undefined.skills.toolsets.group_analysis.message_mix.handler import (
    execute as message_mix_execute,
)


class _FakeOneBot:
    def __init__(
        self,
        *,
        members: list[dict[str, Any]],
        messages: list[dict[str, Any]],
    ) -> None:
        self.members = members
        self.messages = messages
        self.history_calls: list[tuple[int, int | None, int]] = []

    async def get_group_member_list(self, group_id: int) -> list[dict[str, Any]]:
        assert group_id == 123456
        return self.members

    async def get_group_msg_history(
        self,
        group_id: int,
        message_seq: int | None,
        count: int,
    ) -> list[dict[str, Any]]:
        assert group_id == 123456
        self.history_calls.append((group_id, message_seq, count))
        if message_seq is not None:
            return []
        return self.messages[:count]


def _ts(value: str) -> int:
    return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp())


def _message(
    *,
    user_id: int,
    nickname: str,
    time_text: str,
    text: str = "hello",
    segment_type: str = "text",
) -> dict[str, Any]:
    data = {"text": text} if segment_type == "text" else {"file": "pic.jpg"}
    return {
        "message_seq": _ts(time_text),
        "time": _ts(time_text),
        "sender": {"user_id": user_id, "nickname": nickname},
        "message": [{"type": segment_type, "data": data}],
    }


@pytest.mark.asyncio
async def test_member_structure_reports_member_facts() -> None:
    now = datetime.now()
    members = [
        {
            "user_id": 1001,
            "card": "Alice",
            "role": "owner",
            "level": "Lv.42",
            "join_time": int((now - timedelta(days=200)).timestamp()),
            "last_sent_time": int((now - timedelta(days=2)).timestamp()),
        },
        {
            "user_id": 1002,
            "nickname": "Bob",
            "role": "member",
            "level": "12",
            "join_time": int((now - timedelta(days=10)).timestamp()),
            "last_sent_time": int((now - timedelta(days=40)).timestamp()),
        },
        {
            "user_id": 1003,
            "nickname": "Carol",
            "role": "admin",
            "level": "",
            "join_time": int((now - timedelta(days=3)).timestamp()),
            "last_sent_time": 0,
        },
    ]
    onebot = _FakeOneBot(members=members, messages=[])

    result = await member_structure_execute(
        {"group_id": 123456, "example_count": 1},
        {"onebot_client": onebot},
    )

    assert "【群成员结构】群号: 123456" in result
    assert "成员总数: 3" in result
    assert "角色分布:" in result
    assert "群主: 1 人" in result
    assert "管理员: 1 人" in result
    assert "成员: 1 人" in result
    assert "等级概览:" in result
    assert "最高等级: Lv.42" in result
    assert "等级未知: 1 人" in result
    assert "最近 30 天入群: 2 人" in result
    assert "从未发言/无记录: 1 人" in result


@pytest.mark.asyncio
async def test_message_mix_reports_message_facts() -> None:
    messages = [
        _message(
            user_id=1001,
            nickname="Alice",
            time_text="2025-01-20 10:00:00",
            text="今天继续聊插件",
        ),
        _message(
            user_id=1002, nickname="Bob", time_text="2025-01-19 21:00:00", text="收到"
        ),
        _message(
            user_id=1001,
            nickname="Alice",
            time_text="2025-01-18 22:00:00",
            segment_type="image",
        ),
    ]
    onebot = _FakeOneBot(members=[], messages=messages)

    result = await message_mix_execute(
        {
            "group_id": 123456,
            "start_time": "2025-01-01 00:00:00",
            "end_time": "2025-01-20 23:59:59",
            "sample_count": 2,
        },
        {"onebot_client": onebot},
    )

    assert "【群消息构成】群号: 123456" in result
    assert "扫描历史 3 条；窗口有效消息 3 条" in result
    assert "活跃发送者: 2 人" in result
    assert "文本消息: 2 条" in result
    assert "图片消息: 1 条" in result
    assert "活跃时段 Top:" in result
    assert "最近消息样本（2 条）" in result
    assert "今天继续聊插件" in result
    assert onebot.history_calls


@pytest.mark.asyncio
async def test_fact_tools_require_group_id() -> None:
    assert "请提供群号" in await member_structure_execute(
        {}, {"onebot_client": object()}
    )
    assert "请提供群号" in await message_mix_execute({}, {"onebot_client": object()})


@pytest.mark.asyncio
async def test_fact_tools_require_onebot_client() -> None:
    assert "OneBot 客户端未设置" in await member_structure_execute(
        {"group_id": 123456}, {}
    )
    assert "OneBot 客户端未设置" in await message_mix_execute({"group_id": 123456}, {})
