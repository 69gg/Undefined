from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from jmcpy import Book

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
async def test_jm_book_info_mode_returns_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jm_tool, "fetch_book", AsyncMock(return_value=_book()))

    result = await execute({"book_id": "JM350234", "output_mode": "info"}, _context())

    assert "「JM350234 董卓 上+下」" in result
    assert "章节: 1 章" in result
    assert "18comic.vip/album/350234" in result


@pytest.mark.asyncio
async def test_jm_book_info_mode_rejects_bad_book_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch = AsyncMock()
    monkeypatch.setattr(jm_tool, "fetch_book", fetch)

    result = await execute({"book_id": "jm123", "output_mode": "info"}, _context())

    assert "无法解析禁漫车号" in result
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_jm_book_uid_mode_registers_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_attachment = AsyncMock(return_value='PDF: <attachment uid="file_x"/>')
    monkeypatch.setattr(jm_tool, "fetch_jm_book_attachment", fetch_attachment)

    result = await execute({"book_id": "350234", "output_mode": "uid"}, _context())

    assert result == 'PDF: <attachment uid="file_x"/>'
    call = fetch_attachment.await_args
    assert call is not None
    assert call.kwargs["book_id"] == "350234"


@pytest.mark.asyncio
async def test_jm_book_send_mode_uses_current_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    send = AsyncMock(return_value="JM350234 已发送合并转发与 PDF 文件")
    monkeypatch.setattr(jm_tool, "send_jm_book", send)
    monkeypatch.setattr(jm_tool, "fetch_jm_book_attachment", AsyncMock())

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
    monkeypatch.setattr(jm_tool, "send_jm_book", send)

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
