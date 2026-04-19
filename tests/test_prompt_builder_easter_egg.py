"""PromptBuilder 彩蛋功能注入测试"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.ai.prompts import PromptBuilder
from Undefined.end_summary_storage import EndSummaryRecord
from Undefined.memory import Memory


class _FakeEndSummaryStorage:
    async def load(self) -> list[EndSummaryRecord]:
        return []


class _FakeCognitiveService:
    enabled = False

    async def build_context(self, **kwargs: Any) -> str:
        return ""


class _FakeMemoryStorage:
    def get_all(self) -> list[Memory]:
        return []


def _make_builder(
    *,
    keyword_reply_enabled: bool = False,
    repeat_enabled: bool = False,
    inverted_question_enabled: bool = False,
    easter_egg_agent_call_message_mode: str = "none",
) -> PromptBuilder:
    runtime_config = SimpleNamespace(
        keyword_reply_enabled=keyword_reply_enabled,
        repeat_enabled=repeat_enabled,
        inverted_question_enabled=inverted_question_enabled,
        easter_egg_agent_call_message_mode=easter_egg_agent_call_message_mode,
        knowledge_enabled=False,
        grok_search_enabled=False,
        chat_model=SimpleNamespace(
            model_name="gpt-test",
            pool=SimpleNamespace(enabled=False),
            thinking_enabled=False,
            reasoning_enabled=False,
        ),
        vision_model=None,
        agent_model=None,
        embedding_model=None,
        security_model=None,
        grok_model=None,
        cognitive=None,
        memes=None,
    )
    return PromptBuilder(
        bot_qq=123456,
        memory_storage=cast(Any, _FakeMemoryStorage()),
        end_summary_storage=cast(Any, _FakeEndSummaryStorage()),
        runtime_config_getter=lambda: runtime_config,
        anthropic_skill_registry=cast(Any, None),
        cognitive_service=cast(Any, _FakeCognitiveService()),
    )


async def _build_messages(
    builder: PromptBuilder,
    *,
    group_id: int | None = None,
) -> list[dict[str, Any]]:
    async def _fake_load_system_prompt() -> str:
        return "系统提示词"

    async def _fake_load_each_rules() -> str:
        return ""

    async def _fake_recent_messages(
        chat_id: str, msg_type: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        return []

    # Patch internal loaders
    builder._load_system_prompt = _fake_load_system_prompt  # type: ignore[method-assign,unused-ignore]
    builder._load_each_rules = _fake_load_each_rules  # type: ignore[method-assign,unused-ignore]

    extra_context: dict[str, Any] = {}
    if group_id is not None:
        extra_context["group_id"] = group_id

    result = await builder.build_messages(
        '<message sender="测试" sender_id="10001" time="2026-04-17 22:00:00">\n<content>你好</content>\n</message>',
        get_recent_messages_callback=_fake_recent_messages,
        extra_context=extra_context if extra_context else None,
    )
    return list(result)


# ── _build_model_config_info 彩蛋状态 ──


def _get_config_info(builder: PromptBuilder) -> str:
    getter = builder._runtime_config_getter
    assert getter is not None
    info = builder._build_model_config_info(getter())
    return str(info)


def test_model_config_info_shows_easter_egg_disabled() -> None:
    builder = _make_builder()
    info = _get_config_info(builder)
    assert "彩蛋功能: 未启用" in info


def test_model_config_info_shows_keyword_reply_enabled() -> None:
    builder = _make_builder(keyword_reply_enabled=True)
    info = _get_config_info(builder)
    assert "关键词自动回复" in info
    assert "彩蛋功能: " in info


def test_model_config_info_shows_repeat_enabled() -> None:
    builder = _make_builder(repeat_enabled=True)
    info = _get_config_info(builder)
    assert "复读" in info
    assert "连续3条相同消息" in info


def test_model_config_info_shows_repeat_with_inverted_question() -> None:
    builder = _make_builder(repeat_enabled=True, inverted_question_enabled=True)
    info = _get_config_info(builder)
    assert "倒问号" in info
    assert "¿" in info


def test_model_config_info_shows_inverted_question_without_repeat() -> None:
    builder = _make_builder(inverted_question_enabled=True)
    info = _get_config_info(builder)
    assert "倒问号" in info
    assert "复读未启用" in info


def test_model_config_info_shows_agent_call_mode() -> None:
    builder = _make_builder(easter_egg_agent_call_message_mode="clean")
    info = _get_config_info(builder)
    assert "降噪调用提示" in info


# ── 群聊上下文系统行为注入 ──


@pytest.mark.asyncio
async def test_repeat_injection_in_group_context() -> None:
    builder = _make_builder(repeat_enabled=True)
    messages = await _build_messages(builder, group_id=30001)
    system_contents = [m["content"] for m in messages if m["role"] == "system"]
    repeat_injected = any("[系统复读]" in c for c in system_contents)
    assert repeat_injected, "复读彩蛋说明应注入群聊上下文"


@pytest.mark.asyncio
async def test_repeat_injection_not_in_private_context() -> None:
    builder = _make_builder(repeat_enabled=True)
    messages = await _build_messages(builder, group_id=None)
    system_contents = [m["content"] for m in messages if m["role"] == "system"]
    repeat_injected = any("[系统复读]" in c for c in system_contents)
    assert not repeat_injected, "复读彩蛋说明不应注入非群聊上下文"


@pytest.mark.asyncio
async def test_inverted_question_mentioned_in_repeat_injection() -> None:
    builder = _make_builder(repeat_enabled=True, inverted_question_enabled=True)
    messages = await _build_messages(builder, group_id=30001)
    system_contents = [m["content"] for m in messages if m["role"] == "system"]
    inverted_injected = any("倒问号" in c for c in system_contents)
    assert inverted_injected, "倒问号说明应在复读注入中出现"


@pytest.mark.asyncio
async def test_keyword_reply_injection_still_works() -> None:
    builder = _make_builder(keyword_reply_enabled=True)
    messages = await _build_messages(builder, group_id=30001)
    system_contents = [m["content"] for m in messages if m["role"] == "system"]
    keyword_injected = any("[系统关键词自动回复]" in c for c in system_contents)
    assert keyword_injected, "关键词自动回复说明仍应注入"
