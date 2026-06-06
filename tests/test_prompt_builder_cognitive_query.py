from typing import Any, cast

from Undefined.ai.prompts.cognitive import drop_current_message_if_duplicated
from Undefined.ai.prompts import PromptBuilder


class _FakeEndSummaryStorage:
    async def load(self) -> list[dict[str, str]]:
        return []


def _make_builder() -> PromptBuilder:
    return PromptBuilder(
        bot_qq=0,
        memory_storage=None,
        end_summary_storage=cast(Any, _FakeEndSummaryStorage()),
    )


def test_build_cognitive_query_uses_current_frame_raw_content() -> None:
    builder = _make_builder()
    question = """<message sender="测试用户" sender_id="10001" group_id="20001" time="2026-02-24 12:00:00">
<content>帮我排查这个Python报错，日志里提示连接超时和证书失败</content>
</message>

【回复策略】
你可以选择不回复"""
    query, enhanced = builder._build_cognitive_query(
        question,
        extra_context={
            "group_id": 20001,
            "sender_name": "测试用户",
            "group_name": "研发讨论群",
            "is_at_bot": True,
        },
    )
    assert query == "帮我排查这个Python报错，日志里提示连接超时和证书失败"
    assert "回复策略" not in query
    assert enhanced is False


def test_build_cognitive_query_uses_all_messages_in_current_batch() -> None:
    builder = _make_builder()
    question = """<message message_id="101" sender="测试用户" sender_id="10001" group_id="20001" time="2026-02-24 12:00:00">
<content>我周三要发版</content>
</message>
<message message_id="102" sender="测试用户" sender_id="10001" group_id="20001" time="2026-02-24 12:00:02">
<content>补充：是后端服务发版</content>
</message>

【连续消息说明】以上 2 条 <message> 是同一用户连续发送的消息
【回复策略】
你可以选择不回复"""
    query, enhanced = builder._build_cognitive_query(
        question,
        extra_context={
            "group_id": 20001,
            "sender_name": "测试用户",
            "group_name": "研发讨论群",
            "is_at_bot": False,
        },
    )

    assert query.startswith("我周三要发版\n补充：是后端服务发版\n语境: ")
    assert "会话:群聊" in query
    assert "发送者:测试用户" in query
    assert "群:研发讨论群" in query
    assert "连续消息说明" not in query
    assert "回复策略" not in query
    assert enhanced is True


def test_build_cognitive_query_adds_light_context_for_short_content() -> None:
    builder = _make_builder()
    question = """<message sender="测试用户" sender_id="10001" group_id="20001" time="2026-02-24 12:00:00">
<content>这个怎么修</content>
</message>

【回复策略】
你可以选择不回复"""
    query, enhanced = builder._build_cognitive_query(
        question,
        extra_context={
            "group_id": 20001,
            "sender_name": "测试用户",
            "group_name": "研发讨论群",
            "is_at_bot": True,
        },
    )
    assert query.startswith("这个怎么修\n语境: ")
    assert "会话:群聊" in query
    assert "触发:@机器人" in query
    assert "发送者:测试用户" in query
    assert "群:研发讨论群" in query
    assert enhanced is True


def test_build_cognitive_query_falls_back_to_plain_question() -> None:
    builder = _make_builder()
    query, enhanced = builder._build_cognitive_query("直接提问：今天安排啥？")
    assert query == "直接提问：今天安排啥？"
    assert enhanced is False


def test_drop_current_message_if_duplicated_removes_whole_current_batch_tail() -> None:
    recent_messages = [
        {
            "type": "group",
            "message_id": "100",
            "display_name": "其他用户",
            "user_id": "99999",
            "chat_id": "20001",
            "timestamp": "2026-02-24 11:59:00",
            "message": "保留的历史消息",
        },
        {
            "type": "group",
            "message_id": "101",
            "display_name": "测试用户",
            "user_id": "10001",
            "chat_id": "20001",
            "timestamp": "2026-02-24 12:00:00",
            "message": "我周三要发版",
        },
        {
            "type": "group",
            "message_id": "102",
            "display_name": "测试用户",
            "user_id": "10001",
            "chat_id": "20001",
            "timestamp": "2026-02-24 12:00:02",
            "message": "补充：是后端服务发版",
        },
    ]
    question = """<message message_id="101" sender="测试用户" sender_id="10001" group_id="20001" time="2026-02-24 12:00:00">
<content>我周三要发版</content>
</message>
<message message_id="102" sender="测试用户" sender_id="10001" group_id="20001" time="2026-02-24 12:00:02">
<content>补充：是后端服务发版</content>
</message>"""

    filtered = drop_current_message_if_duplicated(recent_messages, question)

    assert [msg["message"] for msg in filtered] == ["保留的历史消息"]
