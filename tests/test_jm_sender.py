from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from unittest.mock import AsyncMock

import pytest
from jmcpy import Book

import Undefined.jm.sender as jm_sender
from Undefined.jm.downloader import JmDownload
from Undefined.jm.sender import (
    generate_pdf_password,
    send_jm_book,
)


def _book() -> Book:
    return Book(
        book_id=1114751,
        title="测试本子",
        authors=("作者A", "作者B"),
        description="这是一段简介。",
        tags=("标签1", "标签2"),
        likes=12,
        views=3456,
        chapters=(),
    )


def _result(tmp_path: Path, *, status: Literal["ok", "oversize"] = "ok") -> JmDownload:
    pdf_path = tmp_path / "JM1114751 测试本子.pdf"
    if status == "ok":
        pdf_path.write_bytes(b"%PDF-1.4")
    return JmDownload(
        status=status,
        book=_book(),
        pdf_path=pdf_path if status == "ok" else None,
        page_count=120,
        size_bytes=12_345_678 if status == "ok" else None,
        chapter_count=3,
        downloaded_chapters=3 if status == "ok" else 1,
        failed_pages=0,
    )


def _sender() -> Any:
    return SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(),
        send_group_forward_message=AsyncMock(),
        send_private_forward_message=AsyncMock(),
        send_group_file=AsyncMock(),
        send_private_file=AsyncMock(),
    )


def _patch_download(
    monkeypatch: pytest.MonkeyPatch, result: JmDownload, task_dir: Path
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def _fake_download(
        book_id: str, *, config: Any, password: str
    ) -> tuple[JmDownload, Path]:
        captured["book_id"] = book_id
        captured["password"] = password
        captured["config"] = config
        return result, task_dir

    monkeypatch.setattr(jm_sender, "download_book_pdf", _fake_download)
    cleanup = AsyncMock()
    monkeypatch.setattr(jm_sender, "cleanup_download_path", cleanup)
    captured["cleanup"] = cleanup
    return captured


def test_generate_pdf_password_uses_safe_eight_char_alphabet() -> None:
    password = generate_pdf_password()

    assert len(password) == 8
    assert all(char in jm_sender._PASSWORD_ALPHABET for char in password)
    # 形近字符不入字母表
    assert not set(password) & set("0O1lI")


@pytest.mark.asyncio
async def test_send_jm_book_sends_three_nodes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sender = _sender()
    result = _result(tmp_path)
    captured = _patch_download(monkeypatch, result, tmp_path / "task")

    status = await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    assert status.startswith("JM1114751 已发送合并转发")
    pdf_path = result.pdf_path
    assert pdf_path is not None
    args = sender.send_group_forward_message.await_args
    nodes = args.args[1]
    assert [node["data"]["name"] for node in nodes] == ["本子信息", "解密密码", "PDF"]
    assert "JM1114751" in nodes[0]["data"]["content"]
    assert "测试本子" in nodes[0]["data"]["content"]
    assert f"：{captured['password']}" in nodes[1]["data"]["content"]
    assert len(captured["password"]) == 8
    file_segment = nodes[2]["data"]["content"][0]
    assert file_segment["type"] == "file"
    assert file_segment["data"]["file"] == f"file://{pdf_path.resolve()}"
    assert file_segment["data"]["name"] == pdf_path.name
    # 历史摘要不含密码，只说明密码在转发节点里
    history_message = args.kwargs["history_message"]
    assert captured["password"] not in history_message
    assert "密码见转发节点" in history_message
    captured["cleanup"].assert_awaited_once_with(tmp_path / "task")


@pytest.mark.asyncio
async def test_send_jm_book_falls_back_to_two_nodes_and_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sender = _sender()
    result = _result(tmp_path)
    calls: list[int] = []

    async def _forward(*args: Any, **kwargs: Any) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("file node rejected")

    sender.send_group_forward_message.side_effect = _forward
    _patch_download(monkeypatch, result, tmp_path / "task")

    await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    assert len(calls) == 2
    second_nodes = sender.send_group_forward_message.await_args.args[1]
    assert [node["data"]["name"] for node in second_nodes] == ["本子信息", "解密密码"]
    pdf_path = result.pdf_path
    assert pdf_path is not None
    sender.send_group_file.assert_awaited_once_with(20001, str(pdf_path), pdf_path.name)
    sender.send_group_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_jm_book_falls_back_to_plain_messages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sender = _sender()
    result = _result(tmp_path)
    sender.send_group_forward_message.side_effect = RuntimeError("forward rejected")
    captured = _patch_download(monkeypatch, result, tmp_path / "task")

    await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    assert sender.send_group_message.await_count == 2
    password_call = sender.send_group_message.await_args_list[1]
    assert captured["password"] in password_call.args[1]
    # 普通消息兜底时历史里同样不留密码
    for call in sender.send_group_message.await_args_list:
        history_message = call.kwargs["history_message"]
        assert history_message is not None
        assert captured["password"] not in history_message
    sender.send_group_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_jm_book_skips_pdf_when_oversize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sender = _sender()
    result = _result(tmp_path, status="oversize")
    _patch_download(monkeypatch, result, tmp_path / "task")

    status = await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    assert status == "JM1114751 已发送信息（PDF 未发送：文件超过体积上限）"
    nodes = sender.send_group_forward_message.await_args.args[1]
    assert [node["data"]["name"] for node in nodes] == ["本子信息", "状态"]
    assert "超过体积上限" in nodes[0]["data"]["content"]
    sender.send_group_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_jm_book_uses_private_forward(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sender = _sender()
    result = _result(tmp_path)
    _patch_download(monkeypatch, result, tmp_path / "task")

    await send_jm_book(
        "1114751",
        sender=sender,
        target_type="private",
        target_id=30001,
        config=SimpleNamespace(),
    )

    sender.send_private_forward_message.assert_awaited_once()
    sender.send_group_forward_message.assert_not_awaited()
    assert sender.send_private_forward_message.await_args.args[0] == 30001
