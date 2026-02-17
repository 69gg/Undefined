"""AgentToolRegistry 单元测试"""

from pathlib import Path
from tempfile import TemporaryDirectory

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
