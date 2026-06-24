from __future__ import annotations

from dataclasses import dataclass
import threading
from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.ai.llm.sanitize import prepare_chat_completion_messages
from Undefined.ai.prompts import PromptBuilder
from Undefined.end_summary_storage import EndSummaryRecord
from Undefined.memory import Memory


class _FakeEndSummaryStorage:
    async def load(self) -> list[EndSummaryRecord]:
        return [
            {
                "summary": "刚刚帮用户定位完问题",
                "timestamp": "2026-04-03 10:00:00",
            }
        ]


class _FakeCognitiveService:
    enabled = True

    async def build_context(self, **kwargs: Any) -> str:
        _ = kwargs
        return "【认知记忆上下文】\n用户最近在排查缓存命中问题。"


class _RecordingCognitiveService:
    enabled = True

    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] | None = None

    async def build_context(self, **kwargs: Any) -> str:
        self.last_kwargs = dict(kwargs)
        return "【认知记忆上下文】\n用户最近在排查缓存命中问题。"


@dataclass
class _FakeAnthropicSkill:
    name: str


class _FakeAnthropicSkillRegistry:
    def has_skills(self) -> bool:
        return True

    def build_metadata_xml(self) -> str:
        return '<skill name="demo_skill" />'

    def get_all_skills(self) -> list[_FakeAnthropicSkill]:
        return [_FakeAnthropicSkill(name="demo_skill")]


class _FakeMemoryStorage:
    def get_all(self) -> list[Memory]:
        return [
            Memory(
                uuid="mem-1",
                fact="用户喜欢详细解释",
                created_at="2026-04-03 09:00:00",
            )
        ]


def _make_builder() -> PromptBuilder:
    runtime_config = SimpleNamespace(
        keyword_reply_enabled=True,
        knowledge_enabled=True,
        grok_search_enabled=True,
        chat_model=SimpleNamespace(
            model_name="gpt-5.4",
            pool=SimpleNamespace(enabled=False),
            thinking_enabled=False,
            reasoning_enabled=True,
        ),
        vision_model=SimpleNamespace(model_name="gpt-4.1-mini"),
        agent_model=SimpleNamespace(model_name="gpt-5.4-mini"),
        embedding_model=SimpleNamespace(model_name="text-embedding-3-small"),
        security_model=SimpleNamespace(model_name="gpt-4.1-mini"),
        grok_model=SimpleNamespace(model_name="grok-4-search"),
        cognitive=SimpleNamespace(enabled=True, recent_end_summaries_inject_k=1),
        memes=SimpleNamespace(
            enabled=True,
            query_default_mode="hybrid",
            allow_gif=True,
            max_source_image_bytes=512000,
        ),
    )
    return PromptBuilder(
        bot_qq=123456,
        memory_storage=cast(Any, _FakeMemoryStorage()),
        end_summary_storage=cast(Any, _FakeEndSummaryStorage()),
        runtime_config_getter=lambda: runtime_config,
        anthropic_skill_registry=cast(Any, _FakeAnthropicSkillRegistry()),
        cognitive_service=cast(Any, _FakeCognitiveService()),
    )


def _make_builder_with_cognitive_service(cognitive_service: Any) -> PromptBuilder:
    runtime_config = SimpleNamespace(
        keyword_reply_enabled=False,
        repeat_enabled=False,
        inverted_question_enabled=False,
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
        cognitive=SimpleNamespace(enabled=True, recent_end_summaries_inject_k=0),
        memes=None,
    )
    return PromptBuilder(
        bot_qq=0,
        memory_storage=None,
        end_summary_storage=cast(Any, _FakeEndSummaryStorage()),
        runtime_config_getter=lambda: runtime_config,
        anthropic_skill_registry=cast(Any, None),
        cognitive_service=cast(Any, cognitive_service),
    )


def _make_builder_with_system_info() -> PromptBuilder:
    runtime_config = SimpleNamespace(
        keyword_reply_enabled=False,
        repeat_enabled=False,
        inverted_question_enabled=False,
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
        cognitive=SimpleNamespace(enabled=False, recent_end_summaries_inject_k=0),
        memes=None,
        prompt_system_info=SimpleNamespace(enabled=True),
    )
    return PromptBuilder(
        bot_qq=0,
        memory_storage=None,
        end_summary_storage=cast(Any, _FakeEndSummaryStorage()),
        runtime_config_getter=lambda: runtime_config,
        anthropic_skill_registry=cast(Any, None),
        cognitive_service=cast(Any, None),
    )


@pytest.mark.asyncio
async def test_build_messages_places_each_rules_before_dynamic_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = _make_builder()

    async def _fake_load_system_prompt() -> str:
        return "系统提示词"

    async def _fake_load_each_rules() -> str:
        return "每次都要先检查缓存"

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
                "chat_name": "研发群",
                "timestamp": "2026-04-03 10:01:00",
                "message": "上一条消息",
                "attachments": [],
                "role": "member",
                "title": "",
            }
        ]

    messages = await builder.build_messages(
        '<message sender="测试用户" sender_id="10001" group_id="20001" time="2026-04-03 10:02:00">\n<content>这次缓存为什么没命中？</content>\n</message>',
        get_recent_messages_callback=_fake_recent_messages,
        extra_context={
            "group_id": 20001,
            "sender_id": 10001,
            "sender_name": "测试用户",
            "group_name": "研发群",
            "request_type": "group",
        },
    )

    labels = {
        "skills": "【可用的 Anthropic Skills】",
        "rules": "【强制规则 - 必须在进行任何操作前仔细阅读并严格遵守】",
        "memory": "【memory.* 手动长期记忆（可编辑）】",
        "cognitive": "【认知记忆上下文】",
        "summary": "【短期行动记录（最近 1 条，带时间）】",
        "history": "【历史消息存档】",
        "time": "【当前时间】",
        "current": "【当前输入批次】",
    }
    positions = {
        name: next(
            idx
            for idx, message in enumerate(messages)
            if marker in str(message.get("content", ""))
        )
        for name, marker in labels.items()
    }

    assert positions["skills"] < positions["rules"] < positions["memory"]
    assert positions["memory"] < positions["cognitive"] < positions["summary"]
    assert positions["summary"] < positions["history"] < positions["time"]
    assert positions["time"] < positions["current"]
    assert all(
        "【当前系统信息】" not in str(message.get("content", ""))
        for message in messages
    )

    runtime_config_message = next(
        str(message.get("content", ""))
        for message in messages
        if "【当前运行环境配置】" in str(message.get("content", ""))
    )
    assert "- 知识库: 已启用" in runtime_config_message
    assert "- 联网搜索: 已启用" in runtime_config_message
    assert (
        "- 表情包库: 已启用（默认检索=hybrid，GIF=允许，入库上限=500KB）"
        in runtime_config_message
    )


@pytest.mark.asyncio
async def test_build_messages_passes_per_message_recall_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cognitive_service = _RecordingCognitiveService()
    builder = _make_builder_with_cognitive_service(cognitive_service)

    async def _fake_load_system_prompt() -> str:
        return "系统提示词"

    async def _fake_load_each_rules() -> str:
        return ""

    monkeypatch.setattr(builder, "_load_system_prompt", _fake_load_system_prompt)
    monkeypatch.setattr(builder, "_load_each_rules", _fake_load_each_rules)

    await builder.build_messages(
        """<message message_id="101" sender="测试用户" sender_id="10001" group_id="20001" time="2026-04-03 10:02:00">
<content>我周三要发版</content>
</message>
<message message_id="102" sender="测试用户" sender_id="10001" group_id="20001" time="2026-04-03 10:02:02">
<content>补充：是后端服务发版</content>
</message>""",
        extra_context={
            "group_id": 20001,
            "sender_id": 10001,
            "sender_name": "测试用户",
            "group_name": "研发群",
            "request_type": "group",
        },
    )

    assert cognitive_service.last_kwargs is not None
    assert cognitive_service.last_kwargs["query"].startswith(
        "我周三要发版\n补充：是后端服务发版\n语境: "
    )
    assert cognitive_service.last_kwargs["recall_queries"] == [
        "我周三要发版\n语境: 会话:群聊; 发送者:测试用户; 群:研发群",
        "补充：是后端服务发版\n语境: 会话:群聊; 发送者:测试用户; 群:研发群",
    ]


@pytest.mark.asyncio
async def test_build_messages_keeps_cache_friendly_static_before_dynamic_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = _make_builder()

    async def _fake_load_system_prompt() -> str:
        return "系统提示词"

    async def _fake_load_each_rules() -> str:
        return "固定规则"

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
                "chat_name": "研发群",
                "timestamp": "2026-04-03 10:01:00",
                "message": "上一条消息",
                "attachments": [],
                "role": "member",
                "title": "",
            }
        ]

    messages = await builder.build_messages(
        '<message sender="测试用户" sender_id="10001" group_id="20001" time="2026-04-03 10:02:00">\n<content>继续看缓存问题</content>\n</message>',
        get_recent_messages_callback=_fake_recent_messages,
        extra_context={
            "group_id": 20001,
            "sender_id": 10001,
            "sender_name": "测试用户",
            "group_name": "研发群",
            "request_type": "group",
        },
    )

    labels = [
        "系统提示词",
        "【当前运行环境配置】",
        "【可用的 Anthropic Skills】",
        "【强制规则 - 必须在进行任何操作前仔细阅读并严格遵守】",
        "【memory.* 手动长期记忆（可编辑）】",
        "【认知记忆上下文】",
        "【短期行动记录（最近 1 条，带时间）】",
        "【历史消息存档】",
        "【当前时间】",
        "【当前输入批次】",
    ]
    positions = [
        next(
            idx
            for idx, message in enumerate(messages)
            if label in str(message.get("content", ""))
        )
        for label in labels
    ]

    assert positions == sorted(positions)
    assert messages[-2]["role"] == "system"
    assert "【当前时间】" in str(messages[-2].get("content", ""))
    assert messages[-1]["role"] == "user"
    assert "【当前输入批次】" in str(messages[-1].get("content", ""))


@pytest.mark.asyncio
async def test_build_messages_places_system_info_before_current_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = _make_builder_with_system_info()

    async def _fake_load_system_prompt() -> str:
        return "系统提示词"

    async def _fake_load_each_rules() -> str:
        return "固定规则"

    monkeypatch.setattr(builder, "_load_system_prompt", _fake_load_system_prompt)
    monkeypatch.setattr(builder, "_load_each_rules", _fake_load_each_rules)
    monkeypatch.setattr(
        "Undefined.ai.prompts.builder.build_prompt_system_info",
        lambda _config: "【当前系统信息】\n- Host: bot-host",
    )

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
                "chat_name": "研发群",
                "timestamp": "2026-04-03 10:01:00",
                "message": "上一条消息",
                "attachments": [],
                "role": "member",
                "title": "",
            }
        ]

    messages = await builder.build_messages(
        '<message sender="测试用户" sender_id="10001" group_id="20001" time="2026-04-03 10:02:00">\n<content>看下系统状态</content>\n</message>',
        get_recent_messages_callback=_fake_recent_messages,
        extra_context={
            "group_id": 20001,
            "sender_id": 10001,
            "sender_name": "测试用户",
            "group_name": "研发群",
            "request_type": "group",
        },
    )

    labels = [
        "【历史消息存档】",
        "【当前系统信息】",
        "【当前时间】",
        "【当前输入批次】",
    ]
    positions = [
        next(
            idx
            for idx, message in enumerate(messages)
            if label in str(message.get("content", ""))
        )
        for label in labels
    ]
    assert positions == sorted(positions)


@pytest.mark.asyncio
async def test_build_messages_collects_system_info_off_event_loop_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = _make_builder_with_system_info()
    event_loop_thread_id = threading.get_ident()
    observed_thread_ids: list[int] = []

    async def _fake_load_system_prompt() -> str:
        return "系统提示词"

    async def _fake_load_each_rules() -> str:
        return ""

    def _fake_build_prompt_system_info(_config: Any) -> str:
        observed_thread_ids.append(threading.get_ident())
        return "【当前系统信息】\n- Host: bot-host"

    monkeypatch.setattr(builder, "_load_system_prompt", _fake_load_system_prompt)
    monkeypatch.setattr(builder, "_load_each_rules", _fake_load_each_rules)
    monkeypatch.setattr(
        "Undefined.ai.prompts.builder.build_prompt_system_info",
        _fake_build_prompt_system_info,
    )

    messages = await builder.build_messages("看下系统状态")

    assert observed_thread_ids
    assert all(thread_id != event_loop_thread_id for thread_id in observed_thread_ids)
    assert any("【当前系统信息】" in str(item.get("content", "")) for item in messages)


@pytest.mark.asyncio
async def test_build_messages_keeps_current_input_batch_as_last_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = PromptBuilder(
        bot_qq=0,
        memory_storage=None,
        end_summary_storage=cast(Any, _FakeEndSummaryStorage()),
    )

    async def _fake_load_system_prompt() -> str:
        return "系统提示词"

    async def _fake_load_each_rules() -> str:
        return "固定规则"

    monkeypatch.setattr(builder, "_load_system_prompt", _fake_load_system_prompt)
    monkeypatch.setattr(builder, "_load_each_rules", _fake_load_each_rules)

    messages = await builder.build_messages("直接提问：缓存是否命中？")

    assert messages[-1]["role"] == "user"
    current_content = str(messages[-1].get("content", ""))
    assert current_content.startswith("【当前输入批次】\n<current_input_batch>\n")
    assert "直接提问：缓存是否命中？" in current_content
    assert "</current_input_batch>" in current_content
    assert "允许你回应和写入 end.observations 的当前输入" in current_content
    assert "不能作为 end.observations 的新事实来源" in current_content


@pytest.mark.asyncio
async def test_system_prompt_as_user_keeps_current_batch_and_readonly_history_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder = PromptBuilder(
        bot_qq=0,
        memory_storage=None,
        end_summary_storage=cast(Any, _FakeEndSummaryStorage()),
    )

    async def _fake_load_system_prompt() -> str:
        return "系统提示词"

    async def _fake_load_each_rules() -> str:
        return "固定规则"

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
                "chat_name": "研发群",
                "timestamp": "2026-04-03 10:01:00",
                "message": "只读历史消息",
                "attachments": [],
                "role": "member",
                "title": "",
            }
        ]

    messages = await builder.build_messages(
        '<message sender="测试用户" sender_id="10001" group_id="20001" time="2026-04-03 10:02:00">\n<content>这次缓存为什么没命中？</content>\n</message>',
        get_recent_messages_callback=_fake_recent_messages,
        extra_context={
            "group_id": 20001,
            "sender_id": 10001,
            "sender_name": "测试用户",
            "group_name": "研发群",
            "request_type": "group",
        },
    )

    cfg: Any = SimpleNamespace(
        reasoning_content_replay=False,
        system_prompt_as_user=True,
    )
    outbound = prepare_chat_completion_messages(cfg, messages)

    assert outbound
    assert all(
        str(message.get("role", "")).lower() not in {"system", "developer"}
        for message in outbound
    )
    assert outbound[0]["role"] == "user"
    merged_content = str(outbound[0].get("content", ""))
    assert "【历史消息存档】（只读上下文）" in merged_content
    assert '<history_archive readonly="true">' in merged_content
    assert "【当前输入批次】" in merged_content
    assert "<current_input_batch>" in merged_content
    assert "这次缓存为什么没命中？" in merged_content
    assert "不能作为 end.observations 的新事实来源" in merged_content
    assert merged_content.index("【历史消息存档】") < merged_content.index(
        "【当前输入批次】"
    )
