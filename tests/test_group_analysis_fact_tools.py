from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from Undefined.skills.toolsets.group_analysis.member_activity.handler import (
    execute as member_activity_execute,
)
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


@pytest.fixture
def activity_onebot() -> _FakeOneBot:
    now = datetime.now()
    return _FakeOneBot(
        members=[
            {
                "user_id": 1001,
                "nickname": "Alice",
                "last_sent_time": int((now - timedelta(hours=1)).timestamp()),
            },
            {
                "user_id": 1002,
                "nickname": "Bob",
                "last_sent_time": int((now - timedelta(days=2)).timestamp()),
            },
            {
                "user_id": 1003,
                "nickname": "Carol",
                "last_sent_time": int((now - timedelta(days=40)).timestamp()),
            },
            {"user_id": 1004, "nickname": "Dave", "last_sent_time": 0},
            {"user_id": 1005, "nickname": "Eve"},
        ],
        messages=[
            _message(user_id=1001, nickname="Alice", time_text="2025-01-21 09:00:00"),
            _message(user_id=1001, nickname="Alice", time_text="2025-01-20 12:00:00"),
            _message(user_id=1002, nickname="Bob", time_text="2025-01-20 11:00:00"),
            _message(user_id=1002, nickname="Bob", time_text="2025-01-20 10:00:00"),
            _message(user_id=1002, nickname="Bob", time_text="2024-12-31 23:00:00"),
        ],
    )


@pytest.mark.asyncio
async def test_member_activity_member_list_reports_recency_not_frequency(
    activity_onebot: _FakeOneBot,
) -> None:
    result = await member_activity_execute(
        {"group_id": 123456, "source": "member_list"},
        {"onebot_client": activity_onebot},
    )

    assert "最近30天内有发言记录: 2" in result
    assert "最后发言早于30天前: 1" in result
    assert "最后发言时间未知: 2" in result
    assert "近期发言成员占比（占总成员）: 40.0%" in result
    assert "最近发言成员 Top 2:" in result
    assert result.index("1. Alice") < result.index("2. Bob")
    assert "最后发言较早成员 Top 1:\n1. Carol" in result
    assert "最后发言时间未知成员 Top 2:\n1. Dave (1004)\n2. Eve (1005)" in result
    assert "不能据此判断发言频率或当前在线状态" in result
    assert "时间未知不代表从未发言" in result
    assert "最活跃成员" not in result
    assert "潜水成员" not in result
    assert "活跃率" not in result
    assert "历史窗口" not in result
    assert activity_onebot.history_calls == []


@pytest.mark.asyncio
async def test_member_activity_history_ranks_window_messages_and_times(
    activity_onebot: _FakeOneBot,
) -> None:
    result = await member_activity_execute(
        {
            "group_id": 123456,
            "source": "history",
            "start_time": "2025-01-01 00:00:00",
            "end_time": "2025-01-20 23:59:59",
        },
        {"onebot_client": activity_onebot},
    )

    assert "历史消息计数: 3 条" in result
    assert "窗口内检索到发言的成员: 2" in result
    assert "窗口消息数排行 Top 2:" in result
    assert "1. Bob (1002) | 窗口消息: 2 | 活跃天数: 1" in result
    assert "2. Alice (1001) | 窗口消息: 1 | 活跃天数: 1" in result
    assert "窗口内最后发言: 2025-01-20 11:00:00" in result
    assert "窗口内最后发言: 2025-01-20 12:00:00" in result
    assert "仅覆盖本次读取到的历史消息" in result
    assert "成员列表最近发言概况" not in result
    assert "最后发言较早成员" not in result
    assert "最后发言时间未知成员" not in result
    assert "综合分" not in result
    assert "Carol" not in result
    assert activity_onebot.history_calls


@pytest.mark.asyncio
async def test_member_activity_history_ties_use_window_last_message(
    activity_onebot: _FakeOneBot,
) -> None:
    activity_onebot.messages = [
        _message(user_id=1002, nickname="Bob", time_text="2025-01-20 11:00:00"),
        _message(user_id=1001, nickname="Alice", time_text="2025-01-20 10:00:00"),
    ]

    result = await member_activity_execute(
        {
            "group_id": 123456,
            "source": "history",
            "start_time": "2025-01-01 00:00:00",
            "end_time": "2025-01-20 23:59:59",
        },
        {"onebot_client": activity_onebot},
    )

    assert "1. Bob (1002) | 窗口消息: 1" in result
    assert "2. Alice (1001) | 窗口消息: 1" in result


@pytest.mark.asyncio
@pytest.mark.parametrize("include_zero", [False, True])
async def test_member_activity_empty_history_does_not_claim_no_one_ever_spoke(
    activity_onebot: _FakeOneBot, include_zero: bool
) -> None:
    activity_onebot.messages = []
    result = await member_activity_execute(
        {
            "group_id": 123456,
            "source": "history",
            "include_zero": include_zero,
            "start_time": "2025-01-01 00:00:00",
            "end_time": "2025-01-20 23:59:59",
        },
        {"onebot_client": activity_onebot},
    )

    assert "历史消息计数: 0 条" in result
    assert "未检索到不等于从未发言，也不能断言整个窗口没有发言" in result
    assert "最近发言成员" not in result
    assert "最后发言较早成员" not in result
    if include_zero:
        assert "窗口消息数排行 Top 5:" in result
        assert result.count("窗口内最后发言: 窗口内未检索到发言") == 5
    else:
        assert "窗口消息数排行 Top" not in result


@pytest.mark.asyncio
async def test_member_activity_default_hybrid_labels_both_sources(
    activity_onebot: _FakeOneBot,
) -> None:
    result = await member_activity_execute(
        {
            "group_id": 123456,
            "start_time": "2025-01-01 00:00:00",
            "end_time": "2025-01-20 23:59:59",
        },
        {"onebot_client": activity_onebot},
    )

    assert "分析模式: hybrid" in result
    assert "成员列表最近发言概况（相对当前时间）" in result
    assert "最后发言时间未知: 2" in result
    assert "混合指标排行 Top 5:" in result
    assert "不是单纯的消息数量排名" in result
    assert "综合分:" in result
    assert "成员列表最后发言: 未知" in result
    assert "最活跃成员" not in result
    assert "潜水成员" not in result
    assert activity_onebot.history_calls
