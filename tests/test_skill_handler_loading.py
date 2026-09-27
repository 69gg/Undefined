from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from Undefined.skills.agents import AgentRegistry
from Undefined.skills.agents.agent_tool_registry import AgentToolRegistry
from Undefined.skills.tools import ToolRegistry
from Undefined.skills.toolsets import ToolSetRegistry

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "Undefined"
SKILLS_ROOT = (PACKAGE_ROOT / "skills").resolve()
AGENT_TOOLS_DIRS = sorted(
    path for path in (SKILLS_ROOT / "agents").glob("*/tools") if path.is_dir()
)


def _write_skill(
    item_dir: Path,
    *,
    name: str,
    handler_source: str,
) -> None:
    item_dir.mkdir(parents=True, exist_ok=True)
    (item_dir / "config.json").write_text(
        json.dumps(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": "test skill",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ),
        encoding="utf-8",
    )
    (item_dir / "handler.py").write_text(handler_source, encoding="utf-8")


def test_all_registered_agents_import_handlers() -> None:
    """随包发布的 agent handler 都必须能导入（含使用相对导入的 agent）。"""
    registry = AgentRegistry(PACKAGE_ROOT / "skills" / "agents")

    assert registry.get_load_failures() == {}
    for name, item in registry._items.items():
        assert item.handler is not None, name
        assert item.loaded is True, name


@pytest.mark.parametrize("relative_base_dir", [False, True])
def test_agent_relative_import_handler_loads(
    monkeypatch: pytest.MonkeyPatch, relative_base_dir: bool
) -> None:
    """handler.py 内的相对导入必须能解析到同目录模块。"""
    monkeypatch.chdir(PACKAGE_ROOT.parent.parent)
    base_dir = SKILLS_ROOT / "agents"
    if relative_base_dir:
        base_dir = base_dir.relative_to(Path.cwd())
    registry = AgentRegistry(base_dir)

    item = registry._items["code_delivery_agent"]
    assert item.module_name == "Undefined.skills.agents.code_delivery_agent.handler"
    assert item.handler is not None
    assert item.handler.__module__ == item.module_name


def test_handler_module_is_canonical_across_import_paths() -> None:
    """按文件路径加载与常规 import 必须得到同一个模块对象。"""
    registry = AgentRegistry(PACKAGE_ROOT / "skills" / "agents")
    item = registry._items["summary_agent"]

    import Undefined.skills.agents.summary_agent.handler as module

    assert item.module_name is not None
    assert sys.modules[item.module_name] is module


def test_toolset_handlers_load_with_canonical_names() -> None:
    registry = ToolSetRegistry(PACKAGE_ROOT / "skills" / "toolsets")

    assert registry.get_load_failures() == {}
    item = registry._items["render.render_latex"]
    assert item.module_name == "Undefined.skills.toolsets.render.render_latex.handler"
    assert item.handler is not None


@pytest.mark.parametrize(
    "tools_dir",
    AGENT_TOOLS_DIRS,
    ids=[path.parent.name for path in AGENT_TOOLS_DIRS],
)
@pytest.mark.parametrize("relative_base_dir", [False, True])
def test_agent_private_tool_handlers_load_with_real_package_names(
    monkeypatch: pytest.MonkeyPatch, tools_dir: Path, relative_base_dir: bool
) -> None:
    """Agent 私有工具的 base_dir 是 ``<agent>/tools``，模块名仍须是真实包路径。

    这是 #97 引入的回归点：按 base_dir 名称上溯一级会把模块算成不存在的
    ``Undefined.skills.tools.<tool>``，导致所有 Agent 私有工具被排除出 schema。
    """
    monkeypatch.chdir(PACKAGE_ROOT.parent.parent)
    if relative_base_dir:
        tools_dir = tools_dir.relative_to(Path.cwd())
    agent_name = tools_dir.parent.name
    registry = AgentToolRegistry(
        tools_dir,
        current_agent_name=agent_name,
        is_main_agent=False,
    )
    local_names = {
        path.name
        for path in tools_dir.iterdir()
        if path.is_dir()
        and (path / "config.json").is_file()
        and (path / "handler.py").is_file()
    }
    local_items = {
        name: item
        for name, item in registry._items.items()
        if item.module_name is not None
    }

    assert registry.skills_root == SKILLS_ROOT
    assert registry.get_load_failures() == {}
    assert local_names
    assert set(local_items) == local_names
    for name, item in local_items.items():
        assert item.handler is not None, name
        assert item.loaded is True, name
        assert item.module_name is not None
        assert item.module_name.startswith(
            f"Undefined.skills.agents.{agent_name}.tools."
        ), item.module_name
        assert item.module_name.endswith(".handler")
        assert item.handler.__module__ == item.module_name
        assert sys.modules[item.module_name].execute is item.handler


def test_file_analysis_multimodal_tool_is_callable() -> None:
    """图片/文件分析依赖的多模态工具必须真的可调用（纯 prompt 层面的失败不可见）。"""
    tools_dir = SKILLS_ROOT / "agents" / "file_analysis_agent" / "tools"
    registry = AgentToolRegistry(
        tools_dir,
        current_agent_name="file_analysis_agent",
        is_main_agent=False,
    )

    item = registry._items["analyze_multimodal"]
    assert item.module_name == (
        "Undefined.skills.agents.file_analysis_agent.tools.analyze_multimodal.handler"
    )
    assert callable(item.handler)
    assert "analyze_multimodal" in {
        schema["function"]["name"] for schema in registry.get_tools_schema()
    }


def test_broken_handler_is_reported_and_hidden_from_schema(tmp_path: Path) -> None:
    tools_dir = tmp_path / "skills" / "tools"
    _write_skill(
        tools_dir / "broken_tool",
        name="broken_tool",
        handler_source=(
            "import definitely_not_installed_module\n\n"
            "async def execute(args, context):\n"
            "    return 'ok'\n"
        ),
    )
    _write_skill(
        tools_dir / "healthy_tool",
        name="healthy_tool",
        handler_source=("async def execute(args, context):\n    return 'ok'\n"),
    )

    registry = ToolRegistry(tools_dir)

    failures = registry.get_load_failures()
    assert "broken_tool" in failures
    assert "definitely_not_installed_module" in failures["broken_tool"]
    assert registry._items["healthy_tool"].load_error is None

    advertised = {schema["function"]["name"] for schema in registry.get_tools_schema()}
    assert advertised == {"healthy_tool"}


def test_handler_without_execute_is_reported(tmp_path: Path) -> None:
    tools_dir = tmp_path / "skills" / "tools"
    _write_skill(
        tools_dir / "no_execute",
        name="no_execute",
        handler_source="VALUE = 1\n",
    )

    registry = ToolRegistry(tools_dir)

    assert "no_execute" in registry.get_load_failures()
    assert registry.get_tools_schema() == []


def test_preload_handlers_returns_failures(tmp_path: Path) -> None:
    tools_dir = tmp_path / "skills" / "tools"
    _write_skill(
        tools_dir / "boom",
        name="boom",
        handler_source="raise RuntimeError('boom at import')\n",
    )

    registry = ToolRegistry(tools_dir)
    failures = registry.preload_handlers()

    assert any(name == "boom" and "boom at import" in error for name, error in failures)


def test_purge_submodules_covers_cross_level_relative_imports() -> None:
    """跨层相对导入的助手模块（from ...docker_utils import）也必须随技能失效。"""
    handler_module = (
        "Undefined.skills.agents.code_delivery_agent.tools.init_docker.handler"
    )
    helper_module = "Undefined.skills.agents.code_delivery_agent.docker_utils"

    registry = AgentRegistry(AgentRegistry(PACKAGE_ROOT / "skills" / "agents").base_dir)
    sys.modules.setdefault(helper_module, object())  # type: ignore[arg-type]
    try:
        registry._purge_submodules(handler_module)
        assert helper_module not in sys.modules
    finally:
        sys.modules.pop(helper_module, None)
