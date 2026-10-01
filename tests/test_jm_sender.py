from __future__ import annotations

from pathlib import Path
import zipfile
from types import SimpleNamespace
from typing import Any, Literal
from unittest.mock import AsyncMock

import pytest
from jmcpy import Book

import Undefined.jm.sender as jm_sender
from Undefined.jm.downloader import (
    ChapterPdfInfo,
    JmChapterArchive,
    JmDownload,
    JmPlainDownload,
)
from Undefined.jm.sender import (
    generate_pdf_password,
    send_jm_book,
)

#: 一个 8 位密码，与 generate_pdf_password 的字母表一致
_PASSWORD = "Ab3xK9Qm"


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


def _archive_result(
    tmp_path: Path,
    *,
    status: Literal["ok", "partial", "empty"] = "ok",
    skipped_chapters: int = 0,
    size_bytes: int | None = None,
) -> JmChapterArchive:
    """自动提取路径的结果：一个装了 N 份章节 PDF 的 zip。"""
    zip_path = tmp_path / "JM1114751 测试本子.zip"
    pdfs = (
        (
            ChapterPdfInfo(
                order=1, chapter_id=111, title="序章", page_count=60, size_bytes=2048
            ),
            ChapterPdfInfo(
                order=2, chapter_id=222, title="", page_count=60, size_bytes=2048
            ),
        )
        if status != "empty"
        else ()
    )
    if status != "empty":
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for pdf in pdfs:
                archive.writestr(f"JM1114751 {pdf.order:03d}.pdf", b"%PDF-1.4")
    if size_bytes is None:
        size_bytes = 12_345_678 if status != "empty" else None
    return JmChapterArchive(
        status=status,
        book=_book(),
        zip_path=zip_path if status != "empty" else None,
        size_bytes=size_bytes,
        page_count=0 if status == "empty" else 120,
        chapter_count=3,
        downloaded_chapters=1 if status == "empty" else 3,
        failed_pages=0,
        skipped_chapters=skipped_chapters,
        pdfs=pdfs,
    )


def _plain_result(
    tmp_path: Path,
    *,
    status: Literal["ok", "oversize", "empty"] = "ok",
    size_bytes: int | None = None,
) -> JmPlainDownload:
    """uid 路径的结果：一份未加密整本 PDF。"""
    pdf_path = tmp_path / "JM1114751 测试本子.pdf"
    if status == "ok":
        pdf_path.write_bytes(b"%PDF-1.4")
    if size_bytes is None:
        size_bytes = 12_345_678 if status == "ok" else None
    return JmPlainDownload(
        status=status,
        book=_book(),
        pdf_path=pdf_path if status == "ok" else None,
        page_count=0 if status == "empty" else 120,
        size_bytes=size_bytes,
        chapter_count=3,
        downloaded_chapters=3 if status == "ok" else 1,
        failed_pages=0,
    )


def _sender() -> Any:
    order: list[str] = []

    def _record(name: str) -> AsyncMock:
        async def _side_effect(*args: Any, **kwargs: Any) -> None:
            order.append(name)

        return AsyncMock(side_effect=_side_effect)

    return SimpleNamespace(
        order=order,
        send_group_message=_record("group_message"),
        send_private_message=_record("private_message"),
        send_group_forward_message=_record("group_forward"),
        send_private_forward_message=_record("private_forward"),
        send_group_file=_record("group_file"),
        send_private_file=_record("private_file"),
    )


def _patch_download(
    monkeypatch: pytest.MonkeyPatch, result: JmDownload, task_dir: Path
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def _fake_download(
        book_id: str, *, config: Any, password: str | None = None
    ) -> tuple[JmDownload, Path]:
        captured["book_id"] = book_id
        captured["password"] = password
        captured["config"] = config
        return result, task_dir

    monkeypatch.setattr(jm_sender, "download_book", _fake_download)
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
async def test_send_jm_book_sends_forward_then_standalone_zip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sender = _sender()
    result = _archive_result(tmp_path)
    captured = _patch_download(monkeypatch, result, tmp_path / "task")

    status = await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    assert status.startswith("JM1114751 已发送合并转发，zip 文件已单独发送")
    assert status.endswith("（2 章 / 120 页 / 11.8MB）")
    zip_path = result.zip_path
    assert zip_path is not None
    args = sender.send_group_forward_message.await_args
    nodes = args.args[1]
    # 文件不进转发：转发节点里的文件在 QQ 客户端下载会失败
    assert [node["data"]["name"] for node in nodes] == ["本子信息", "解密密码"]
    assert all(isinstance(node["data"]["content"], str) for node in nodes)
    info_text = nodes[0]["data"]["content"]
    assert "JM1114751" in info_text
    assert "测试本子" in info_text
    # 信息节点说明每章一份 PDF 与 zip 大小
    assert "本次出 2 份 PDF" in info_text
    assert "zip: 11.8MB" in info_text
    # 末尾展示可复制的车号，不再放站点链接
    assert info_text.strip().endswith("JM1114751")
    assert "18comic" not in info_text
    # 密码节点写明这是 zip 内所有 PDF 共用的密码
    assert "zip 内所有 PDF 的解密密码" in nodes[1]["data"]["content"]
    assert f"：{captured['password']}" in nodes[1]["data"]["content"]
    assert len(captured["password"]) == 8
    # 可下载的入口是转发之后那条独立文件消息
    sender.send_group_file.assert_awaited_once_with(20001, str(zip_path), zip_path.name)
    assert sender.order == ["group_forward", "group_file"]
    # 历史摘要不含密码，只说明密码在转发节点里；文件还没上传，不能提前声称已发送
    history_message = args.kwargs["history_message"]
    assert captured["password"] not in history_message
    assert "密码见转发节点" in history_message
    assert "随后单独发送" in history_message
    assert "已单独发送" not in history_message
    assert "每章一份" in history_message
    captured["cleanup"].assert_awaited_once_with(tmp_path / "task")


@pytest.mark.asyncio
async def test_send_jm_book_mentions_skipped_chapters_in_info(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """被跳过的章节必须写在用户看得到的地方，不能静默少发。"""
    sender = _sender()
    result = _archive_result(tmp_path, status="partial", skipped_chapters=2)
    _patch_download(monkeypatch, result, tmp_path / "task")

    await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    info_text = sender.send_group_forward_message.await_args.args[1][0]["data"][
        "content"
    ]
    assert "2 章未打包" in info_text
    # partial 仍然照发 zip
    sender.send_group_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_jm_book_falls_back_to_plain_messages_then_zip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sender = _sender()
    result = _archive_result(tmp_path)
    sender.send_group_forward_message.side_effect = RuntimeError("forward rejected")
    captured = _patch_download(monkeypatch, result, tmp_path / "task")

    await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    # 转发发不出去时才退化为两条普通消息，zip 照旧单独发送
    assert sender.order == ["group_message", "group_message", "group_file"]
    password_call = sender.send_group_message.await_args_list[1]
    assert captured["password"] in password_call.args[1]
    assert "zip 内所有 PDF 的解密密码" in password_call.args[1]
    # 普通消息兜底时历史里同样不留密码
    for call in sender.send_group_message.await_args_list:
        history_message = call.kwargs["history_message"]
        assert history_message is not None
        assert captured["password"] not in history_message
    zip_path = result.zip_path
    assert zip_path is not None
    sender.send_group_file.assert_awaited_once_with(20001, str(zip_path), zip_path.name)


@pytest.mark.asyncio
async def test_send_jm_book_keeps_sending_file_when_forward_is_uncertain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """转发投递结果未确认时不降级重发，但独立文件消息此前从未发出，必须照发。"""

    class _Uncertain(RuntimeError):
        delivery_uncertain = True

    sender = _sender()
    result = _archive_result(tmp_path)
    sender.send_group_forward_message.side_effect = _Uncertain("timeout")
    _patch_download(monkeypatch, result, tmp_path / "task")

    status = await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    # 转发可能已经送达，绝不重发转发或信息/密码
    assert sender.send_group_forward_message.await_count == 1
    sender.send_group_message.assert_not_awaited()
    # 文件丢在这里等于整本下载白跑
    sender.send_group_file.assert_awaited_once()
    assert "合并转发投递结果未确认" in status
    assert "zip 文件已单独发送" in status


@pytest.mark.asyncio
async def test_send_jm_book_does_not_resend_when_forward_transfer_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _TransferFailed(RuntimeError):
        file_transfer_error = True

    sender = _sender()
    result = _archive_result(tmp_path)
    sender.send_group_forward_message.side_effect = _TransferFailed("prepare failed")
    _patch_download(monkeypatch, result, tmp_path / "task")

    status = await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    sender.send_group_message.assert_not_awaited()
    sender.send_group_file.assert_awaited_once()
    assert "合并转发投递结果未确认" in status


@pytest.mark.asyncio
async def test_send_jm_book_does_not_retry_when_file_delivery_is_uncertain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """文件自身投递结果未确认时同样不重发（仓库约定），也不补发任何提示。"""

    class _Uncertain(RuntimeError):
        delivery_uncertain = True

    sender = _sender()
    result = _archive_result(tmp_path)
    sender.send_group_file.side_effect = _Uncertain("timeout")
    _patch_download(monkeypatch, result, tmp_path / "task")

    with pytest.raises(_Uncertain):
        await send_jm_book(
            "1114751",
            sender=sender,
            target_type="group",
            target_id=20001,
            config=SimpleNamespace(),
        )

    assert sender.send_group_file.await_count == 1
    sender.send_group_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_jm_book_does_not_retry_when_file_transfer_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _TransferFailed(RuntimeError):
        file_transfer_error = True

    sender = _sender()
    result = _archive_result(tmp_path)
    sender.send_group_file.side_effect = _TransferFailed("prepare failed")
    _patch_download(monkeypatch, result, tmp_path / "task")

    with pytest.raises(_TransferFailed):
        await send_jm_book(
            "1114751",
            sender=sender,
            target_type="group",
            target_id=20001,
            config=SimpleNamespace(),
        )

    assert sender.send_group_file.await_count == 1
    sender.send_group_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_jm_book_reports_when_zip_upload_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sender = _sender()
    result = _archive_result(tmp_path)
    sender.send_group_file.side_effect = RuntimeError("upload failed")
    _patch_download(monkeypatch, result, tmp_path / "task")

    status = await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    assert status.startswith("JM1114751 已发送合并转发，zip 文件发送失败"), status
    last = sender.send_group_message.await_args_list[-1]
    assert "zip 上传失败" in last.args[1]
    assert "信息与密码如上" in last.args[1]
    # 提示写入历史：转发摘要只说「随后发送」，真正发没发出去靠这条收口
    assert last.args[2] is True


@pytest.mark.asyncio
async def test_send_jm_book_upload_failure_notice_avoids_claiming_uncertain_forward(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """转发投递未确认 + 文件也失败时，提示不能说「信息与密码如上」。"""

    class _Uncertain(RuntimeError):
        delivery_uncertain = True

    sender = _sender()
    result = _archive_result(tmp_path)
    sender.send_group_forward_message.side_effect = _Uncertain("timeout")
    sender.send_group_file.side_effect = RuntimeError("upload failed")
    _patch_download(monkeypatch, result, tmp_path / "task")

    status = await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    assert status.startswith("JM1114751 合并转发投递结果未确认，zip 文件发送失败"), (
        status
    )
    notice = sender.send_group_message.await_args_list[-1].args[1]
    assert "投递结果未确认" in notice
    assert "信息与密码如上" not in notice
    # 转发本身不重发，这里只发一条提示
    assert sender.send_group_message.await_count == 1


@pytest.mark.asyncio
async def test_send_jm_book_reports_fallback_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sender = _sender()
    result = _archive_result(tmp_path)
    sender.send_group_forward_message.side_effect = RuntimeError("forward rejected")
    _patch_download(monkeypatch, result, tmp_path / "task")

    status = await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    assert "已改为普通消息发送信息与密码" in status
    assert "zip 文件已单独发送" in status


@pytest.mark.asyncio
async def test_send_jm_book_skips_file_when_no_chapter_pdf_was_built(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """一章都没出时不发密码与文件，只发信息与状态两个节点。"""
    sender = _sender()
    result = _archive_result(tmp_path, status="empty", skipped_chapters=3)
    _patch_download(monkeypatch, result, tmp_path / "task")

    status = await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    assert "JM1114751 已发送信息" in status
    nodes = sender.send_group_forward_message.await_args.args[1]
    assert [node["data"]["name"] for node in nodes] == ["本子信息", "状态"]
    assert "3 章未打包" in nodes[0]["data"]["content"]
    sender.send_group_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_jm_book_skips_file_when_nothing_downloaded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sender = _sender()
    result = _archive_result(tmp_path, status="empty")
    _patch_download(monkeypatch, result, tmp_path / "task")

    status = await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    assert status == "JM1114751 已发送信息（文件未发送：没有下载到任何页面）"
    nodes = sender.send_group_forward_message.await_args.args[1]
    assert "没有下载到任何页面" in nodes[0]["data"]["content"]
    sender.send_group_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_jm_book_empty_result_does_not_show_size_as_zip_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """没有 zip 时信息节点不能把原图字节写成 zip 大小。"""
    sender = _sender()
    result = _archive_result(tmp_path, status="empty")
    _patch_download(monkeypatch, result, tmp_path / "task")

    await send_jm_book(
        "1114751",
        sender=sender,
        target_type="group",
        target_id=20001,
        config=SimpleNamespace(),
    )

    info = sender.send_group_forward_message.await_args.args[1][0]["data"]["content"]
    assert "zip:" not in info


@pytest.mark.asyncio
async def test_send_jm_book_uses_private_forward(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sender = _sender()
    result = _archive_result(tmp_path)
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
    # 私聊同样单独发文件，而不是把文件塞进转发
    sender.send_private_file.assert_awaited_once()
    sender.send_group_file.assert_not_awaited()


def test_format_jm_book_info_lists_metadata() -> None:
    text = jm_sender.format_jm_book_info(_book())

    assert "「JM1114751 测试本子」" in text
    assert "作者: 作者A, 作者B" in text
    assert "章节: 1 章" in text
    assert "标签: 标签1、标签2" in text
    assert "观看 3456 | 点赞 12" in text
    assert "车号: JM1114751" in text
    assert "18comic.vip/album/1114751" in text


@pytest.mark.asyncio
async def test_fetch_jm_book_attachment_registers_unencrypted_pdf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _plain_result(tmp_path)
    captured = _patch_download(monkeypatch, result, tmp_path / "task")
    record = SimpleNamespace(uid="file_jm123")
    registry = SimpleNamespace(register_local_file=AsyncMock(return_value=record))

    text = await jm_sender.fetch_jm_book_attachment(
        book_id="1114751",
        attachment_registry=registry,
        scope_key="group:20001",
        config=SimpleNamespace(),
    )

    # uid 模式必须输出未加密 PDF，否则 PDF 解析工具打不开
    assert captured["password"] is None
    register_args = registry.register_local_file.await_args
    assert register_args.args[0] == "group:20001"
    assert register_args.kwargs["kind"] == "file"
    assert register_args.kwargs["source_kind"] == "jm_book"
    assert 'PDF: <attachment uid="file_jm123"/>' in text
    assert "该 PDF 未加密" in text
    captured["cleanup"].assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_jm_book_attachment_requires_scope_and_registry(
    tmp_path: Path,
) -> None:
    assert "attachment_registry" in await jm_sender.fetch_jm_book_attachment(
        book_id="1114751",
        attachment_registry=None,
        scope_key="group:20001",
        config=SimpleNamespace(),
    )
    assert "作用域" in await jm_sender.fetch_jm_book_attachment(
        book_id="1114751",
        attachment_registry=SimpleNamespace(register_local_file=AsyncMock()),
        scope_key="  ",
        config=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_fetch_jm_book_attachment_reports_oversize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = _plain_result(tmp_path, status="oversize")
    captured = _patch_download(monkeypatch, result, tmp_path / "task")
    registry = SimpleNamespace(register_local_file=AsyncMock())

    text = await jm_sender.fetch_jm_book_attachment(
        book_id="1114751",
        attachment_registry=registry,
        scope_key="group:20001",
        config=SimpleNamespace(),
    )

    assert "PDF 超过单章体积上限" in text
    registry.register_local_file.assert_not_awaited()
    captured["cleanup"].assert_awaited_once()
