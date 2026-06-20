from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from Undefined.skills.agents import AgentRegistry
from Undefined.skills.agents.undefined_self_code_agent.tools.glob import (
    handler as glob_handler,
)
from Undefined.skills.agents.undefined_self_code_agent.tools.list_directory import (
    handler as list_handler,
)
from Undefined.skills.agents.undefined_self_code_agent.tools.read_file import (
    handler as read_handler,
)
from Undefined.skills.agents.undefined_self_code_agent.tools.search_file_content import (
    handler as search_handler,
)


AGENT_DIR = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "Undefined"
    / "skills"
    / "agents"
    / "undefined_self_code_agent"
)


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src" / "Undefined").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "tests").mkdir()
    (root / "res").mkdir()
    (root / "docs").mkdir()
    (root / "apps" / "undefined-chat" / "src").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "logs").mkdir()
    (root / "code" / "NagaAgent").mkdir(parents=True)

    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (root / "README.md").write_text("# Undefined\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text("## Unreleased\n", encoding="utf-8")
    (root / "ARCHITECTURE.md").write_text("AgentRegistry\n", encoding="utf-8")
    (root / "config.toml.example").write_text(
        "[models.agent]\nmodel_name = 'x'\n", encoding="utf-8"
    )
    (root / "src" / "Undefined" / "main.py").write_text(
        "def run() -> None:\n    print('Undefined')\n", encoding="utf-8"
    )
    (root / "src" / "Undefined" / ".hidden.py").write_text(
        "hidden = True\n", encoding="utf-8"
    )
    (root / "scripts" / "tool.py").write_text("print('tool')\n", encoding="utf-8")
    (root / "tests" / "test_main.py").write_text(
        "def test_main() -> None:\n    assert True\n", encoding="utf-8"
    )
    (root / "res" / "prompt.txt").write_text("prompt\n", encoding="utf-8")
    (root / "docs" / "usage.md").write_text("usage docs\n", encoding="utf-8")
    (root / "apps" / "undefined-chat" / "src" / "App.tsx").write_text(
        "export const App = () => 'chat';\n", encoding="utf-8"
    )
    (root / "data" / "secret.txt").write_text("secret\n", encoding="utf-8")
    (root / "logs" / "run.log").write_text("log\n", encoding="utf-8")
    (root / "code" / "NagaAgent" / "main.py").write_text("naga\n", encoding="utf-8")
    (root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    return root


def _context(root: Path) -> dict[str, Any]:
    return {"repo_root": root}


def test_config_json_schema() -> None:
    cfg: dict[str, Any] = json.loads((AGENT_DIR / "config.json").read_text("utf-8"))
    function = cfg["function"]

    assert cfg["type"] == "function"
    assert function["name"] == "undefined_self_code_agent"
    assert function["parameters"]["required"] == ["prompt"]
    assert "prompt" in function["parameters"]["properties"]


def test_agent_registry_loads_description_from_intro() -> None:
    registry = AgentRegistry(AGENT_DIR.parent)
    schema = {
        item["function"]["name"]: item["function"]["description"]
        for item in registry.get_agents_schema()
    }

    assert "undefined_self_code_agent" in schema
    assert "Undefined 自身代码查阅助手" in schema["undefined_self_code_agent"]
    assert "只读查阅" in schema["undefined_self_code_agent"]


@pytest.mark.asyncio
async def test_read_file_allows_allowed_paths(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)

    result = await read_handler.execute(
        {"file_path": "src/Undefined/main.py"},
        _context(root),
    )

    assert "=== src/Undefined/main.py" in result
    assert "def run() -> None" in result


@pytest.mark.asyncio
async def test_read_file_allows_config_example_root_file(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)

    result = await read_handler.execute(
        {"file_path": "config.toml.example"},
        _context(root),
    )

    assert "[models.agent]" in result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        ".env",
        "data/secret.txt",
        "logs/run.log",
        "code/NagaAgent/main.py",
        "src/Undefined/.hidden.py",
        "../outside.txt",
    ],
)
async def test_read_file_rejects_disallowed_paths(tmp_path: Path, path: str) -> None:
    root = _make_repo(tmp_path)

    result = await read_handler.execute({"file_path": path}, _context(root))

    assert "权限不足" in result
    assert "允许目录" in result


@pytest.mark.asyncio
async def test_list_directory_root_only_lists_allowed_scope(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)

    result = await list_handler.execute({}, _context(root))

    assert "📁 src/" in result
    assert "📄 README.md" in result
    assert "data/" not in result
    assert "pyproject.toml" not in result


@pytest.mark.asyncio
async def test_glob_only_returns_allowed_files(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)

    result = await glob_handler.execute({"pattern": "**/*.py"}, _context(root))

    assert "src/Undefined/main.py" in result
    assert "scripts/tool.py" in result
    assert "tests/test_main.py" in result
    assert "code/NagaAgent/main.py" not in result


@pytest.mark.asyncio
async def test_search_only_returns_allowed_files(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)

    result = await search_handler.execute(
        {"pattern": "secret", "case_sensitive": False},
        _context(root),
    )

    assert "data/secret.txt" not in result
    assert ".env" not in result
    assert "未找到匹配" in result


@pytest.mark.asyncio
async def test_search_can_find_allowed_content(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)

    result = await search_handler.execute(
        {"pattern": "Undefined", "path": "src", "include": "*.py"},
        _context(root),
    )

    assert "src/Undefined/main.py:2:" in result


@pytest.mark.asyncio
async def test_binary_file_is_rejected(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    binary = root / "src" / "Undefined" / "asset.bin"
    binary.write_bytes(b"\x00\x01\x02")

    result = await read_handler.execute(
        {"file_path": "src/Undefined/asset.bin"},
        _context(root),
    )

    assert "不是可读取的文本文件" in result
