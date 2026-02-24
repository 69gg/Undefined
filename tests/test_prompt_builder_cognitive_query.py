from typing import Any, cast

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
