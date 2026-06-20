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
from Undefined.utils import io as async_io


AGENT_DIR = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "Undefined"
    / "skills"
    / "agents"
    / "undefined_self_code_agent"
)


async def _make_repo(tmp_path: Path) -> Path:
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

    await async_io.write_text(root / "pyproject.toml", "[project]\nname='x'\n")
    await async_io.write_text(root / "README.md", "# Undefined\n")
    await async_io.write_text(root / "CHANGELOG.md", "## Unreleased\n")
    await async_io.write_text(root / "ARCHITECTURE.md", "AgentRegistry\n")
    await async_io.write_text(
        root / "config.toml.example",
        "[models.agent]\nmodel_name = 'x'\n",
    )
    await async_io.write_text(
        root / "src" / "Undefined" / "main.py",
        "def run() -> None:\n    print('Undefined')\n",
    )
    await async_io.write_text(
        root / "src" / "Undefined" / ".hidden.py",
        "hidden = True\n",
    )
    await async_io.write_text(root / "scripts" / "tool.py", "print('tool')\n")
    await async_io.write_text(
        root / "tests" / "test_main.py",
        "def test_main() -> None:\n    assert True\n",
    )
    await async_io.write_text(root / "res" / "prompt.txt", "prompt\n")
    await async_io.write_text(root / "docs" / "usage.md", "usage docs\n")
    await async_io.write_text(
        root / "apps" / "undefined-chat" / "src" / "App.tsx",
        "export const App = () => 'chat';\n",
    )
    await async_io.write_text(root / "data" / "secret.txt", "secret\n")
    await async_io.write_text(root / "logs" / "run.log", "log\n")
    await async_io.write_text(root / "code" / "NagaAgent" / "main.py", "naga\n")
    await async_io.write_text(root / ".env", "TOKEN=secret\n")
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
    assert (
        "`code/NagaAgent/` 是 NagaAgent 子模块" in schema["undefined_self_code_agent"]
    )


def test_prompt_and_intro_exclude_naga_submodule() -> None:
    prompt = (AGENT_DIR / "prompt.md").read_text("utf-8")
    intro = (AGENT_DIR / "intro.md").read_text("utf-8")

    assert "`code/NagaAgent/` 是 NagaAgent 子模块" in prompt
    assert "永远不属于 Undefined 自身代码查阅范围" in prompt
    assert "`code/NagaAgent/` 是 NagaAgent 子模块" in intro
    assert "不属于 Undefined 自身代码查阅范围" in intro


@pytest.mark.asyncio
async def test_read_file_allows_allowed_paths(tmp_path: Path) -> None:
    root = await _make_repo(tmp_path)

    result = await read_handler.execute(
        {"file_path": "src/Undefined/main.py"},
        _context(root),
    )

    assert "=== src/Undefined/main.py" in result
    assert "def run() -> None" in result


@pytest.mark.asyncio
async def test_read_file_allows_config_example_root_file(tmp_path: Path) -> None:
    root = await _make_repo(tmp_path)

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
    root = await _make_repo(tmp_path)

    result = await read_handler.execute({"file_path": path}, _context(root))

    assert "权限不足" in result
    assert "允许目录" in result


@pytest.mark.asyncio
async def test_list_directory_root_only_lists_allowed_scope(tmp_path: Path) -> None:
    root = await _make_repo(tmp_path)

    result = await list_handler.execute({}, _context(root))

    assert "📁 src/" in result
    assert "📄 README.md" in result
    assert "data/" not in result
    assert "pyproject.toml" not in result


@pytest.mark.asyncio
async def test_glob_only_returns_allowed_files(tmp_path: Path) -> None:
    root = await _make_repo(tmp_path)

    result = await glob_handler.execute({"pattern": "**/*.py"}, _context(root))

    assert "src/Undefined/main.py" in result
    assert "scripts/tool.py" in result
    assert "tests/test_main.py" in result
    assert "code/NagaAgent/main.py" not in result


@pytest.mark.asyncio
async def test_glob_handles_allowed_root_files(tmp_path: Path) -> None:
    root = await _make_repo(tmp_path)

    result = await glob_handler.execute({"pattern": "*.md"}, _context(root))

    assert "README.md" in result
    assert "CHANGELOG.md" in result


@pytest.mark.asyncio
async def test_glob_handles_recursive_pattern_for_allowed_root_files(
    tmp_path: Path,
) -> None:
    root = await _make_repo(tmp_path)

    result = await glob_handler.execute({"pattern": "**/*.md"}, _context(root))

    assert "README.md" in result
    assert "docs/usage.md" in result


@pytest.mark.asyncio
@pytest.mark.parametrize("pattern", ["../*.py", "/tmp/*.py", "src/../*.py"])
async def test_glob_rejects_traversal_patterns(
    tmp_path: Path,
    pattern: str,
) -> None:
    root = await _make_repo(tmp_path)

    result = await glob_handler.execute({"pattern": pattern}, _context(root))

    assert "glob 模式无效" in result


@pytest.mark.asyncio
async def test_search_only_returns_allowed_files(tmp_path: Path) -> None:
    root = await _make_repo(tmp_path)

    result = await search_handler.execute(
        {"pattern": "secret", "case_sensitive": False},
        _context(root),
    )

    assert "data/secret.txt" not in result
    assert ".env" not in result
    assert "未找到匹配" in result


@pytest.mark.asyncio
async def test_search_can_find_allowed_content(tmp_path: Path) -> None:
    root = await _make_repo(tmp_path)

    result = await search_handler.execute(
        {"pattern": "Undefined", "path": "src", "include": "*.py"},
        _context(root),
    )

    assert "src/Undefined/main.py:2:" in result


@pytest.mark.asyncio
async def test_binary_file_is_rejected(tmp_path: Path) -> None:
    root = await _make_repo(tmp_path)
    binary = root / "src" / "Undefined" / "asset.bin"
    await async_io.write_bytes(binary, b"\x00\x01\x02")

    result = await read_handler.execute(
        {"file_path": "src/Undefined/asset.bin"},
        _context(root),
    )

    assert "不是可读取的文本文件" in result


@pytest.mark.asyncio
async def test_read_file_empty_line_window_has_valid_header(tmp_path: Path) -> None:
    root = await _make_repo(tmp_path)
    empty_path = root / "src" / "Undefined" / "empty.py"
    await async_io.write_text(empty_path, "")

    result = await read_handler.execute(
        {"file_path": "src/Undefined/empty.py", "offset": 1, "limit": 10},
        _context(root),
    )

    assert "行 0-0/0（空文件）" in result
    assert "行 1-0/0" not in result
