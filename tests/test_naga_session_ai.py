"""会话级 Naga 策略：提示词路径与工具暴露/执行应同步变化。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.ai.client.setup import ClientSetupMixin
from Undefined.ai.prompts.builder import PromptBuilder
from Undefined.ai.prompts.system_context import select_system_prompt_path
from Undefined.ai.tooling import ToolManager
from Undefined.config.models import NagaConfig
from Undefined.context import RequestContext
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


def _runtime(
    *,
    nagaagent: bool = True,
    mode: str = "off",
    allowed_group_ids: set[int] | None = None,
    allowed_private_ids: set[int] | None = None,
    blocked_group_ids: set[int] | None = None,
    blocked_private_ids: set[int] | None = None,
    superadmin_qq: int = 0,
) -> Any:
    return SimpleNamespace(
        nagaagent_mode_enabled=nagaagent,
        superadmin_qq=superadmin_qq,
        is_superadmin=lambda uid: superadmin_qq > 0 and int(uid) == int(superadmin_qq),
        naga=NagaConfig(
            mode=mode,
            allowed_group_ids=frozenset(allowed_group_ids or set()),
            blocked_group_ids=frozenset(blocked_group_ids or set()),
            allowed_private_ids=frozenset(allowed_private_ids or set()),
            blocked_private_ids=frozenset(blocked_private_ids or set()),
        ),
        keyword_reply_enabled=False,
        repeat_enabled=False,
        inverted_question_enabled=False,
        easter_egg_agent_call_message_mode="none",
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
        prompt_system_info=None,
    )


def _make_builder(cfg: Any) -> PromptBuilder:
    return PromptBuilder(
        bot_qq=0,
        memory_storage=cast(Any, _FakeMemoryStorage()),
        end_summary_storage=cast(Any, _FakeEndSummaryStorage()),
        system_prompt_path="res/prompts/undefined.xml",
        runtime_config_getter=lambda: cfg,
        anthropic_skill_registry=cast(Any, None),
        cognitive_service=cast(Any, _FakeCognitiveService()),
    )


def _make_client(cfg: Any) -> Any:
    client = cast(Any, ClientSetupMixin.__new__(ClientSetupMixin))
    client.runtime_config = cfg
    client._get_runtime_config = lambda: cfg
    return client


def _tool(name: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name}}


def test_select_system_prompt_path_follows_group_allowlist() -> None:
    cfg = _runtime(mode="allowlist", allowed_group_ids={100})

    allowed = select_system_prompt_path(
        default_path="res/prompts/undefined.xml",
        runtime_config_getter=lambda: cfg,
        group_id=100,
        request_type="group",
    )
    denied = select_system_prompt_path(
        default_path="res/prompts/undefined.xml",
        runtime_config_getter=lambda: cfg,
        group_id=999,
        request_type="group",
    )
    assert allowed == "res/prompts/undefined_nagaagent.xml"
    assert denied == "res/prompts/undefined.xml"


def test_select_system_prompt_path_follows_private_blacklist() -> None:
    cfg = _runtime(mode="blacklist", blocked_private_ids={55})

    ok = select_system_prompt_path(
        default_path="res/prompts/undefined.xml",
        runtime_config_getter=lambda: cfg,
        user_id=1,
        request_type="private",
    )
    blocked = select_system_prompt_path(
        default_path="res/prompts/undefined.xml",
        runtime_config_getter=lambda: cfg,
        user_id=55,
        request_type="private",
    )
    assert ok == "res/prompts/undefined_nagaagent.xml"
    assert blocked == "res/prompts/undefined.xml"


def test_prompt_builder_resolves_nagaagent_from_extra_context() -> None:
    cfg = _runtime(mode="allowlist", allowed_group_ids={42})
    builder = _make_builder(cfg)
    assert builder._resolve_nagaagent_active({"request_type": "group", "group_id": 42})
    assert not builder._resolve_nagaagent_active(
        {"request_type": "group", "group_id": 1}
    )


@pytest.mark.asyncio
async def test_prompt_builder_loads_naga_prompt_for_allowed_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _runtime(mode="allowlist", allowed_group_ids={7})
    builder = _make_builder(cfg)
    loaded: list[str] = []

    def _fake_read(path: str) -> str:
        loaded.append(path)
        return f"PROMPT:{path}"

    monkeypatch.setattr(
        "Undefined.ai.prompts.builder.read_text_resource",
        _fake_read,
    )

    content = await builder._load_system_prompt(
        nagaagent_active=builder._resolve_nagaagent_active(
            {"request_type": "group", "group_id": 7}
        )
    )
    assert loaded[-1] == "res/prompts/undefined_nagaagent.xml"
    assert "undefined_nagaagent.xml" in content

    content_denied = await builder._load_system_prompt(
        nagaagent_active=builder._resolve_nagaagent_active(
            {"request_type": "group", "group_id": 8}
        )
    )
    assert loaded[-1] == "res/prompts/undefined.xml"
    assert content_denied.endswith("undefined.xml") or "undefined.xml" in content_denied


@pytest.mark.asyncio
async def test_tool_execute_denies_via_request_context_without_context_ids() -> None:
    """execute_tool 先注入 RequestContext，再拦截未放行会话的 naga agent。"""
    cfg = _runtime(mode="allowlist", allowed_group_ids={100})
    manager = cast(Any, ToolManager.__new__(ToolManager))

    # context 故意不带 group_id/user_id/request_type
    async with RequestContext(
        request_type="group", group_id=999, sender_id=1, user_id=1
    ):
        result = await ToolManager.execute_tool(
            manager,
            "naga_code_analysis_agent",
            {},
            {"runtime_config": cfg},
        )
    assert result == "该功能未启用"


def test_tool_filter_and_prompt_stay_in_sync_for_group_and_private() -> None:
    """同一会话策略下：工具 schema 过滤与提示词路径结论一致。"""
    group_cfg = _runtime(mode="allowlist", allowed_group_ids={100})
    private_cfg = _runtime(mode="allowlist", allowed_private_ids={88})
    tools = [_tool("send_message"), _tool("naga_code_analysis_agent")]

    group_client = _make_client(group_cfg)
    denied_g = group_client._filter_tools_for_runtime_config(
        tools, group_id=999, request_type="group"
    )
    allowed_g = group_client._filter_tools_for_runtime_config(
        tools, group_id=100, request_type="group"
    )
    assert "naga_code_analysis_agent" not in [t["function"]["name"] for t in denied_g]
    assert "naga_code_analysis_agent" in [t["function"]["name"] for t in allowed_g]
    assert (
        select_system_prompt_path(
            default_path="res/prompts/undefined.xml",
            runtime_config_getter=lambda: group_cfg,
            group_id=999,
            request_type="group",
        )
        == "res/prompts/undefined.xml"
    )
    assert (
        select_system_prompt_path(
            default_path="res/prompts/undefined.xml",
            runtime_config_getter=lambda: group_cfg,
            group_id=100,
            request_type="group",
        )
        == "res/prompts/undefined_nagaagent.xml"
    )

    private_client = _make_client(private_cfg)
    denied_p = private_client._filter_tools_for_runtime_config(
        tools, user_id=1, request_type="private"
    )
    allowed_p = private_client._filter_tools_for_runtime_config(
        tools, user_id=88, request_type="private"
    )
    assert "naga_code_analysis_agent" not in [t["function"]["name"] for t in denied_p]
    assert "naga_code_analysis_agent" in [t["function"]["name"] for t in allowed_p]
    assert (
        select_system_prompt_path(
            default_path="res/prompts/undefined.xml",
            runtime_config_getter=lambda: private_cfg,
            user_id=1,
            request_type="private",
        )
        == "res/prompts/undefined.xml"
    )
    assert (
        select_system_prompt_path(
            default_path="res/prompts/undefined.xml",
            runtime_config_getter=lambda: private_cfg,
            user_id=88,
            request_type="private",
        )
        == "res/prompts/undefined_nagaagent.xml"
    )


def test_master_off_disables_prompt_and_tools_regardless_of_lists() -> None:
    cfg = _runtime(
        nagaagent=False,
        mode="allowlist",
        allowed_group_ids={1},
        allowed_private_ids={1},
    )
    client = _make_client(cfg)
    tools = [_tool("naga_code_analysis_agent"), _tool("end")]
    filtered = client._filter_tools_for_runtime_config(
        tools, group_id=1, request_type="group"
    )
    assert [t["function"]["name"] for t in filtered] == ["end"]
    assert (
        select_system_prompt_path(
            default_path="res/prompts/undefined.xml",
            runtime_config_getter=lambda: cfg,
            group_id=1,
            request_type="group",
        )
        == "res/prompts/undefined.xml"
    )
