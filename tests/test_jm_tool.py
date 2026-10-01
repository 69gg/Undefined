from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from jmcpy import Book

import Undefined.skills.shared as skills_shared
import Undefined.skills.tools.jm_book.handler as jm_tool
from Undefined.skills.tools.jm_book.handler import execute


def _book() -> Book:
    return Book(book_id=350234, title="董卓 上+下", authors=("作者A",), tags=("标签",))


def _context(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "runtime_config": SimpleNamespace(),
        "sender": SimpleNamespace(),
        "request_type": "group",
        "group_id": 1074091596,
        "attachment_registry": SimpleNamespace(register_local_file=AsyncMock()),
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_jm_book_info_mode_forwards_normalized_book_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = AsyncMock(return_value="「JM350234 董卓 上+下」\n车号: JM350234")
    monkeypatch.setattr(jm_tool, "jm_book_info_text", info)

    result = await execute({"book_id": "JM350234", "output_mode": "info"}, _context())

    assert result.startswith("「JM350234 董卓 上+下」")
    call = info.await_args
    assert call is not None
    assert call.args[0] == "350234"


@pytest.mark.asyncio
async def test_jm_book_info_mode_rejects_bad_book_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch = AsyncMock()
    monkeypatch.setattr(jm_tool, "jm_normalize_book_id", lambda _value: None)
    fetch = AsyncMock()
    monkeypatch.setattr(jm_tool, "jm_book_info_text", fetch)

    result = await execute({"book_id": "jm123", "output_mode": "info"}, _context())

    assert "无法解析禁漫车号" in result
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_jm_book_uid_mode_registers_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_attachment = AsyncMock(return_value='PDF: <attachment uid="file_x"/>')
    monkeypatch.setattr(jm_tool, "jm_book_attachment_text", fetch_attachment)

    result = await execute({"book_id": "350234", "output_mode": "uid"}, _context())

    assert result == 'PDF: <attachment uid="file_x"/>'
    call = fetch_attachment.await_args
    assert call is not None
    assert call.args[0] == "350234"


@pytest.mark.asyncio
async def test_jm_book_send_mode_uses_current_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    send = AsyncMock(return_value="JM350234 已发送合并转发与 PDF 文件")
    monkeypatch.setattr(jm_tool, "jm_send_book", send)
    monkeypatch.setattr(jm_tool, "jm_book_attachment_text", AsyncMock())

    result = await execute({"book_id": "jm350234"}, _context())

    assert result == "JM350234 已发送合并转发与 PDF 文件"
    call = send.await_args
    assert call is not None
    assert call.kwargs["target_type"] == "group"
    assert call.kwargs["target_id"] == 1074091596


@pytest.mark.asyncio
async def test_jm_book_send_mode_accepts_explicit_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    send = AsyncMock(return_value="ok")
    monkeypatch.setattr(jm_tool, "jm_send_book", send)

    await execute(
        {
            "book_id": "350234",
            "target_type": "private",
            "target_id": 20001,
        },
        _context(request_type="group", group_id=999),
    )

    call = send.await_args
    assert call is not None
    assert call.kwargs["target_type"] == "private"
    assert call.kwargs["target_id"] == 20001


@pytest.mark.asyncio
async def test_jm_book_rejects_unknown_output_mode() -> None:
    result = await execute({"book_id": "350234", "output_mode": "pdf"}, _context())

    assert "output_mode 只能是" in result


@pytest.mark.asyncio
async def test_jm_book_reports_missing_runtime_config() -> None:
    result = await execute({"book_id": "350234"}, _context(runtime_config=None))

    assert result == "缺少必要的运行时组件（runtime_config）"


def test_jm_book_tool_definition_is_sendable_to_file_agent() -> None:
    import json
    from pathlib import Path

    tool_dir = (
        Path(__file__).resolve().parents[1] / "src/Undefined/skills/tools/jm_book"
    )
    config = json.loads((tool_dir / "config.json").read_text(encoding="utf-8"))
    callable_config = json.loads(
        (tool_dir / "callable.json").read_text(encoding="utf-8")
    )

    assert config["function"]["name"] == "jm_book"
    assert set(config["function"]["parameters"]["required"]) == {"book_id"}
    assert callable_config["allowed_callers"] == ["file_analysis_agent"]


@pytest.mark.asyncio
async def test_jm_book_uid_mode_requires_runtime_config() -> None:
    result = await execute(
        {"book_id": "350234", "output_mode": "uid"}, _context(runtime_config=None)
    )

    assert result == "缺少必要的运行时组件（runtime_config）"


@pytest.mark.asyncio
async def test_jm_book_send_mode_requires_sender() -> None:
    result = await execute({"book_id": "350234"}, _context(sender=None))

    assert result == "缺少必要的运行时组件（sender）"


@pytest.mark.asyncio
async def test_jm_book_send_mode_needs_a_target_session() -> None:
    result = await execute(
        {"book_id": "350234"},
        _context(request_type=None, group_id=None, user_id=None),
    )

    assert "无法确定目标会话" in result


@pytest.mark.asyncio
async def test_jm_book_rejects_invalid_target_arguments() -> None:
    bad_type = await execute(
        {"book_id": "350234", "target_type": "channel", "target_id": 1}, _context()
    )
    assert "target_type 只能是" in bad_type

    bad_id = await execute(
        {"book_id": "350234", "target_type": "group", "target_id": "abc"}, _context()
    )
    assert "target_id 必须是整数" in bad_id


@pytest.mark.asyncio
async def test_jm_book_uid_mode_falls_back_to_scope_from_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_attachment = AsyncMock(return_value="ok")
    monkeypatch.setattr(jm_tool, "jm_book_attachment_text", fetch_attachment)
    monkeypatch.setattr(jm_tool, "jm_scope_key", lambda _ctx: "group:1074091596")

    await execute({"book_id": "350234", "output_mode": "uid"}, _context())

    call = fetch_attachment.await_args
    assert call is not None
    assert call.kwargs["scope_key"] == "group:1074091596"


@pytest.mark.asyncio
async def test_jm_book_reports_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jm_tool,
        "jm_book_info_text",
        AsyncMock(side_effect=RuntimeError("源站 403")),
    )

    result = await execute({"book_id": "350234", "output_mode": "info"}, _context())

    assert "禁漫本子处理失败" in result
    assert "源站 403" in result


# --- skills/shared.py 的 JM 桥接：handler 不越界导入，由这里转发 ---


def test_shared_jm_normalize_book_id_accepts_ids_and_links() -> None:
    assert skills_shared.jm_normalize_book_id("JM350234") == "350234"
    assert skills_shared.jm_normalize_book_id("https://18comic.vip/album/350234") == (
        "350234"
    )
    assert skills_shared.jm_normalize_book_id("hello") is None


def test_shared_jm_scope_key_prefers_context_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert skills_shared.jm_scope_key({"scope_key": " group:1 "}) == "group:1"

    import Undefined.attachments as attachments_module

    monkeypatch.setattr(
        attachments_module, "scope_from_context", lambda _ctx: "private:2"
    )
    assert skills_shared.jm_scope_key({"user_id": 2}) == "private:2"


@pytest.mark.asyncio
async def test_shared_jm_bridge_forwards_to_domain_functions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import Undefined.jm.downloader as jm_downloader_module
    import Undefined.jm.sender as jm_sender_module

    monkeypatch.setattr(
        jm_downloader_module, "fetch_book", AsyncMock(return_value=_book())
    )
    info = await skills_shared.jm_book_info_text("350234", config=SimpleNamespace())
    assert "JM350234" in info

    attachment = AsyncMock(return_value="uid-ok")
    monkeypatch.setattr(jm_sender_module, "fetch_jm_book_attachment", attachment)
    assert (
        await skills_shared.jm_book_attachment_text(
            "350234",
            registry="registry",
            scope_key="group:1",
            config="config",
        )
        == "uid-ok"
    )
    assert attachment.await_args is not None
    assert attachment.await_args.kwargs["attachment_registry"] == "registry"

    send = AsyncMock(return_value="sent")
    monkeypatch.setattr(jm_sender_module, "send_jm_book", send)
    assert (
        await skills_shared.jm_send_book(
            "350234",
            sender="sender",
            target_type="group",
            target_id=20001,
            config="config",
        )
        == "sent"
    )
    assert send.await_args is not None
    assert send.await_args.kwargs["target_id"] == 20001


def test_jm_book_handler_has_no_out_of_skills_imports() -> None:
    """handler 必须只依赖 skills/ 内部（依赖经 shared 转发）。"""
    import ast
    from pathlib import Path

    handler_path = (
        Path(__file__).resolve().parents[1]
        / "src/Undefined/skills/tools/jm_book/handler.py"
    )
    tree = ast.parse(handler_path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            modules.add(node.module or "")
    out_of_skills = {
        name
        for name in modules
        if name == "Undefined"
        or (name.startswith("Undefined.") and not name.startswith("Undefined.skills"))
    }
    assert out_of_skills == set()
