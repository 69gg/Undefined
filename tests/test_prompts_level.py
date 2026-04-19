from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.ai.prompts import PromptBuilder
from Undefined.end_summary_storage import EndSummaryRecord


class _FakeEndSummaryStorage:
    async def load(self) -> list[EndSummaryRecord]:
        return []


class _FakeCognitiveService:
    enabled = False


class _FakeAnthropicSkillRegistry:
    def has_skills(self) -> bool:
        return False


def _make_builder() -> PromptBuilder:
    """创建用于测试的 PromptBuilder 实例"""
    runtime_config = SimpleNamespace(
        keyword_reply_enabled=False,
        knowledge_enabled=False,
        grok_search_enabled=False,
        chat_model=SimpleNamespace(
            model_name="gpt-4.1",
            pool=SimpleNamespace(enabled=False),
            thinking_enabled=False,
            reasoning_enabled=False,
        ),
        vision_model=SimpleNamespace(model_name="gpt-4.1-mini"),
        agent_model=SimpleNamespace(model_name="gpt-4.1-mini"),
        embedding_model=SimpleNamespace(model_name="text-embedding-3-small"),
        security_model=SimpleNamespace(model_name="gpt-4.1-mini"),
        grok_model=SimpleNamespace(model_name="grok-4-search"),
        cognitive=SimpleNamespace(enabled=False, recent_end_summaries_inject_k=0),
        memes=SimpleNamespace(
            enabled=False,
            query_default_mode="hybrid",
            allow_gif=False,
            max_source_image_bytes=512000,
        ),
    )
    return PromptBuilder(
        bot_qq=123456,
        memory_storage=None,
        end_summary_storage=cast(Any, _FakeEndSummaryStorage()),
        runtime_config_getter=lambda: runtime_config,
        anthropic_skill_registry=cast(Any, _FakeAnthropicSkillRegistry()),
        cognitive_service=cast(Any, _FakeCognitiveService()),
    )


@pytest.mark.asyncio
async def test_group_message_with_level_includes_level_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试群消息有 level 时 XML 包含 level 属性"""
    builder = _make_builder()

    async def _fake_load_system_prompt() -> str:
        return "系统提示词"

    async def _fake_load_each_rules() -> str:
        return "规则"

    monkeypatch.setattr(builder, "_load_system_prompt", _fake_load_system_prompt)
    monkeypatch.setattr(builder, "_load_each_rules", _fake_load_each_rules)

    async def _fake_recent_messages(
        chat_id: str, msg_type: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        _ = chat_id, msg_type, start, end
        return [
            {
                "type": "group",
                "display_name": "测试用户",
                "user_id": "10001",
                "chat_id": "20001",
                "chat_name": "测试群",
                "timestamp": "2026-04-11 10:00:00",
                "message": "测试消息",
                "attachments": [],
                "role": "member",
                "title": "",
                "level": "Lv.5",
            }
        ]

    messages = await builder.build_messages(
        '<message sender="测试用户" sender_id="10001">测试</message>',
        get_recent_messages_callback=_fake_recent_messages,
        extra_context={
            "group_id": 20001,
            "sender_id": 10001,
            "sender_name": "测试用户",
            "group_name": "测试群",
            "request_type": "group",
        },
    )

    history_message = next(
        str(msg.get("content", ""))
        for msg in messages
        if "【历史消息存档】" in str(msg.get("content", ""))
    )

    assert 'level="Lv.5"' in history_message
    assert "<message" in history_message


@pytest.mark.asyncio
async def test_group_message_with_empty_level_excludes_level_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试群消息 level 为空字符串时 XML 不包含 level 属性"""
    builder = _make_builder()

    async def _fake_load_system_prompt() -> str:
        return "系统提示词"

    async def _fake_load_each_rules() -> str:
        return "规则"

    monkeypatch.setattr(builder, "_load_system_prompt", _fake_load_system_prompt)
    monkeypatch.setattr(builder, "_load_each_rules", _fake_load_each_rules)

    async def _fake_recent_messages(
        chat_id: str, msg_type: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        _ = chat_id, msg_type, start, end
        return [
            {
                "type": "group",
                "display_name": "测试用户",
                "user_id": "10001",
                "chat_id": "20001",
                "chat_name": "测试群",
                "timestamp": "2026-04-11 10:00:00",
                "message": "测试消息",
                "attachments": [],
                "role": "member",
                "title": "",
                "level": "",
            }
        ]

    messages = await builder.build_messages(
        '<message sender="测试用户" sender_id="10001">测试</message>',
        get_recent_messages_callback=_fake_recent_messages,
        extra_context={
            "group_id": 20001,
            "sender_id": 10001,
            "sender_name": "测试用户",
            "group_name": "测试群",
            "request_type": "group",
        },
    )

    history_message = next(
        str(msg.get("content", ""))
        for msg in messages
        if "【历史消息存档】" in str(msg.get("content", ""))
    )

    assert "level=" not in history_message
    assert "<message" in history_message


@pytest.mark.asyncio
async def test_group_message_without_level_key_excludes_level_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试群消息没有 level 键时 XML 不包含 level 属性"""
    builder = _make_builder()

    async def _fake_load_system_prompt() -> str:
        return "系统提示词"

    async def _fake_load_each_rules() -> str:
        return "规则"

    monkeypatch.setattr(builder, "_load_system_prompt", _fake_load_system_prompt)
    monkeypatch.setattr(builder, "_load_each_rules", _fake_load_each_rules)

    async def _fake_recent_messages(
        chat_id: str, msg_type: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        _ = chat_id, msg_type, start, end
        return [
            {
                "type": "group",
                "display_name": "测试用户",
                "user_id": "10001",
                "chat_id": "20001",
                "chat_name": "测试群",
                "timestamp": "2026-04-11 10:00:00",
                "message": "测试消息",
                "attachments": [],
                "role": "member",
                "title": "",
            }
        ]

    messages = await builder.build_messages(
        '<message sender="测试用户" sender_id="10001">测试</message>',
        get_recent_messages_callback=_fake_recent_messages,
        extra_context={
            "group_id": 20001,
            "sender_id": 10001,
            "sender_name": "测试用户",
            "group_name": "测试群",
            "request_type": "group",
        },
    )

    history_message = next(
        str(msg.get("content", ""))
        for msg in messages
        if "【历史消息存档】" in str(msg.get("content", ""))
    )

    assert "level=" not in history_message
    assert "<message" in history_message


@pytest.mark.asyncio
async def test_private_message_never_has_level_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试私聊消息无论是否有 level 都不会出现 level 属性"""
    builder = _make_builder()

    async def _fake_load_system_prompt() -> str:
        return "系统提示词"

    async def _fake_load_each_rules() -> str:
        return "规则"

    monkeypatch.setattr(builder, "_load_system_prompt", _fake_load_system_prompt)
    monkeypatch.setattr(builder, "_load_each_rules", _fake_load_each_rules)

    async def _fake_recent_messages(
        chat_id: str, msg_type: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        _ = chat_id, msg_type, start, end
        return [
            {
                "type": "private",
                "display_name": "测试用户",
                "user_id": "10001",
                "chat_id": "10001",
                "chat_name": "QQ用户10001",
                "timestamp": "2026-04-11 10:00:00",
                "message": "私聊测试消息",
                "attachments": [],
                "level": "Lv.10",
            }
        ]

    messages = await builder.build_messages(
        '<message sender="测试用户" sender_id="10001">测试</message>',
        get_recent_messages_callback=_fake_recent_messages,
        extra_context={
            "sender_id": 10001,
            "sender_name": "测试用户",
            "request_type": "private",
        },
    )

    history_message = next(
        str(msg.get("content", ""))
        for msg in messages
        if "【历史消息存档】" in str(msg.get("content", ""))
    )

    assert "level=" not in history_message
    assert "<message" in history_message
