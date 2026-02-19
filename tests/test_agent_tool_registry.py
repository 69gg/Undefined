"""AgentToolRegistry 单元测试"""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from Undefined.skills.agents.agent_tool_registry import AgentToolRegistry


class TestFindSkillsRoot:
    """测试 _find_skills_root 方法"""

    def test_find_skills_root_success(self) -> None:
        """测试成功找到 skills 根目录"""
        with TemporaryDirectory() as tmpdir:
            # 创建目录结构: tmpdir/skills/agents/test_agent
            skills_dir = Path(tmpdir) / "skills"
            agents_dir = skills_dir / "agents"
            test_agent_dir = agents_dir / "test_agent"
            test_agent_dir.mkdir(parents=True)

            registry = AgentToolRegistry(test_agent_dir)
            result = registry._find_skills_root()

            assert result == skills_dir

    def test_find_skills_root_depth_limit(self) -> None:
        """测试深度限制：超过 10 层返回 None"""
        with TemporaryDirectory() as tmpdir:
            # 创建深度超过 10 层的目录结构
            current = Path(tmpdir)
            for i in range(12):
                current = current / f"level{i}"
            current.mkdir(parents=True)

            registry = AgentToolRegistry(current)
            result = registry._find_skills_root()

            # 应该返回 None，因为超过深度限制
            assert result is None

    def test_find_skills_root_not_found(self) -> None:
        """测试找不到 skills 目录"""
        with TemporaryDirectory() as tmpdir:
            # 创建一个不包含 skills 目录的结构
            test_dir = Path(tmpdir) / "some" / "path"
            test_dir.mkdir(parents=True)

            registry = AgentToolRegistry(test_dir)
            result = registry._find_skills_root()

            assert result is None


class _DummySender:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, bool]] = []

    async def send_group_message(
        self, group_id: int, message: str, mark_sent: bool = False
    ) -> None:
        self.messages.append((group_id, message, mark_sent))


class _DummyAgentRegistry:
    async def execute_agent(
        self, agent_name: str, args: dict[str, object], context: dict[str, object]
    ) -> str:
        return f"ok:{agent_name}:{args.get('prompt', '')}"


class _DummyAIClient:
    def __init__(self) -> None:
        self.agent_registry = _DummyAgentRegistry()


class TestAgentCallEasterEgg:
    @pytest.mark.asyncio
    async def test_agent_to_agent_easter_egg_message_format(self) -> None:
        with TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            tools_dir = Path(tmpdir) / "tools"
            tools_dir.mkdir(parents=True)
            registry = AgentToolRegistry(tools_dir, current_agent_name="web_agent")

            sender = _DummySender()
            context = {
                "agent_name": "web_agent",
                "ai_client": _DummyAIClient(),
                "runtime_config": SimpleNamespace(
                    easter_egg_agent_call_message_mode="agent"
                ),
                "sender": sender,
                "group_id": 123456,
            }
            handler = registry._create_agent_call_handler("info_agent", ["web_agent"])

            result = await handler({"prompt": "hello"}, context)

            assert result == "ok:info_agent:hello"
            assert sender.messages == [
                (
                    123456,
                    "web_agent：info_agent，我调用你了，我要调用你了！",
                    False,
                )
            ]

    @pytest.mark.asyncio
    async def test_skip_agent_tool_easter_egg_for_call_agent_tool(self) -> None:
        with TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            tools_dir = Path(tmpdir) / "tools"
            tools_dir.mkdir(parents=True)
            registry = AgentToolRegistry(tools_dir, current_agent_name="web_agent")

            registry._callable_agent_tool_names.add("call_info_agent")
            sender = _DummySender()
            context = {
                "agent_name": "web_agent",
                "runtime_config": SimpleNamespace(
                    easter_egg_agent_call_message_mode="all"
                ),
                "sender": sender,
                "group_id": 123456,
            }

            await registry._maybe_send_agent_tool_call_easter_egg(
                "call_info_agent", context
            )

            assert sender.messages == []
