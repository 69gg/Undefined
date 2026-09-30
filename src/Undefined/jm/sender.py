"""禁漫自动提取的合并转发发送。

一次发送固定三个节点：本子信息、PDF 解密密码、PDF 文件。QQ 对合并转发节点内
的 ``file`` 段支持并不确定，因此三节点发送失败时自动退化为「两节点转发（信息 +
密码）+ 单独 PDF 文件消息」，密码始终不会写进历史。
"""

from __future__ import annotations

import logging
from pathlib import Path
import secrets
from typing import TYPE_CHECKING, Any, Literal

from jmcpy import Book

from Undefined.jm.downloader import (
    JmDownload,
    cleanup_download_path,
    download_book_pdf,
)

if TYPE_CHECKING:
    from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)

_BOT_NAME = "Undefined"
_DEFAULT_BOT_UIN = "10000"
#: 密码位数固定 8 位
PASSWORD_LENGTH = 8
#: 去掉形近字符（0/O、1/l/I），方便在手机上输入
_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
#: 公开站点车号链接（仅用于信息节点展示）
_ALBUM_URL_TEMPLATE = "https://18comic.vip/album/{book_id}"
_DESCRIPTION_PREVIEW_CHARS = 200
_MAX_TAGS = 10


def generate_pdf_password(length: int = PASSWORD_LENGTH) -> str:
    """生成 PDF 打开密码。"""
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def build_album_url(book_id: int | str) -> str:
    return _ALBUM_URL_TEMPLATE.format(book_id=book_id)


def _node(content: str | list[dict[str, Any]], *, name: str) -> dict[str, Any]:
    return {
        "type": "node",
        "data": {
            "name": name,
            "uin": _DEFAULT_BOT_UIN,
            "content": content,
        },
    }


def _format_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "未知"
    return f"{size_bytes / 1024 / 1024:.1f}MB"


def _preview(text: str | None, limit: int = _DESCRIPTION_PREVIEW_CHARS) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def build_info_text(result: JmDownload, *, note: str = "") -> str:
    """信息节点（也是历史摘要的来源）的正文。"""
    book: Book = result.book
    lines = [f"「JM{book.book_id} {book.title or '未知标题'}」"]

    if book.authors:
        lines.append(f"作者: {', '.join(book.authors)}")
    lines.append(
        f"章节: {result.chapter_count} 章（本次合并 {result.downloaded_chapters} 章）"
    )
    if book.tags:
        lines.append(f"标签: {'、'.join(book.tags[:_MAX_TAGS])}")

    stats: list[str] = []
    if book.views is not None:
        stats.append(f"观看 {book.views}")
    if book.likes is not None:
        stats.append(f"点赞 {book.likes}")
    if stats:
        lines.append(" | ".join(stats))

    summary = f"页数: {result.page_count}"
    if result.size_bytes is not None:
        summary += f" | PDF: {_format_size(result.size_bytes)}"
    lines.append(summary)
    if result.failed_pages:
        lines.append(f"下载失败 {result.failed_pages} 页")
    if note:
        lines.append(note)

    description = _preview(book.description)
    if description and description != book.title:
        lines.extend(["---", description])

    lines.extend(["---", build_album_url(book.book_id)])
    return "\n".join(lines)


def build_password_text(password: str) -> str:
    return f"PDF 解密密码（{len(password)} 位）：{password}"


def build_forward_nodes(
    info_text: str,
    *,
    pdf_path: Path | None = None,
    password: str = "",
    status_text: str = "",
) -> list[dict[str, Any]]:
    """构建合并转发节点：信息 / 密码或状态 / PDF 文件。

    PDF 节点保留在转发里（文件在本地合成后随转发一起上传，群聊下会成为真正的群文件）。
    但 QQ 客户端拿不到**转发节点内**文件元素的下载地址，点击会报「获取发送地址失败」
    （该文案只存在于 QQ 客户端；NapCat 侧上传与发送都是成功的），所以调用方还要把同一个
    文件作为独立文件消息再发一次，用户才有可用的下载入口。
    """
    if pdf_path is None:
        if not password:
            # 没有可发送的 PDF 时用状态说明替代密码与文件节点
            return [
                _node(info_text, name="本子信息"),
                _node(status_text or "PDF 未发送", name="状态"),
            ]
        return [
            _node(info_text, name="本子信息"),
            _node(build_password_text(password), name="解密密码"),
        ]
    return [
        _node(info_text, name="本子信息"),
        _node(build_password_text(password), name="解密密码"),
        _node(
            [
                {
                    "type": "file",
                    "data": {
                        "file": f"file://{pdf_path.resolve()}",
                        "name": pdf_path.name,
                    },
                }
            ],
            name="PDF",
        ),
    ]


def build_history_message(result: JmDownload) -> str:
    """历史摘要：只写可复述的信息，不含 PDF 密码。"""
    book = result.book
    lines = [
        f"[JM] 「{book.title or '未知标题'}」",
        f"车号: JM{book.book_id}",
        f"章节: {result.chapter_count} 章 | 页数: {result.page_count}",
    ]
    if result.ok:
        lines.append(
            f"PDF: 已发送加密文件（{_format_size(result.size_bytes)}，密码见转发节点）"
        )
    else:
        lines.append("PDF: 未发送")
    lines.append(build_album_url(book.book_id))
    return "\n".join(lines)


async def _send_forward(
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    nodes: list[dict[str, Any]],
    *,
    history_message: str,
) -> None:
    if target_type == "group":
        await sender.send_group_forward_message(
            target_id, nodes, history_message=history_message
        )
    else:
        await sender.send_private_forward_message(
            target_id, nodes, history_message=history_message
        )


async def _send_text(
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    message: str,
    *,
    history_message: str | None = None,
) -> None:
    if target_type == "group":
        await sender.send_group_message(
            target_id, message, history_message=history_message
        )
    else:
        await sender.send_private_message(
            target_id, message, history_message=history_message
        )


async def _send_file(
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    file_path: str,
    file_name: str,
) -> None:
    if target_type == "group":
        await sender.send_group_file(target_id, file_path, file_name)
    else:
        await sender.send_private_file(target_id, file_path, file_name)


async def _send_result(
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    *,
    book_id: str,
    info_text: str,
    password: str,
    pdf_path: Path,
    history_message: str,
) -> None:
    """先发「信息 + 密码 + PDF」三节点合并转发，再补一条独立文件消息。

    转发里的 PDF 节点是需求要求的结构，但 QQ 客户端点它下载会报「获取发送地址失败」
    （见 build_forward_nodes 的说明）；独立文件消息才是用户真正能下载的入口。两者用
    同一个本地文件：群聊下按内容去重，不会重复占用群空间（``stream`` / ``url`` 传输
    模式下字节会再传一遍给协议端）。
    """
    nodes = build_forward_nodes(info_text, pdf_path=pdf_path, password=password)
    try:
        await _send_forward(
            sender, target_type, target_id, nodes, history_message=history_message
        )
    except Exception:
        logger.exception("[JM] 合并转发失败，回退为普通消息: book=%s", book_id)
        # 历史里不留密码：历史摘要与用户可见正文分开
        await _send_text(
            sender,
            target_type,
            target_id,
            info_text,
            history_message=history_message,
        )
        await _send_text(
            sender,
            target_type,
            target_id,
            build_password_text(password),
            history_message=history_message,
        )

    try:
        await _send_file(
            sender, target_type, target_id, str(pdf_path), str(pdf_path.name)
        )
    except Exception:
        logger.exception("[JM] PDF 文件发送失败: book=%s", book_id)
        try:
            await _send_text(
                sender,
                target_type,
                target_id,
                "PDF 上传失败，本次没有发送文件（信息与密码如上）。",
            )
        except Exception:
            pass


async def send_jm_book(
    book_id: str,
    *,
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    config: Any,
) -> str:
    """下载整本并发送合并转发，返回可记录的状态说明。"""
    password = generate_pdf_password()
    result, task_dir = await download_book_pdf(
        book_id, config=config, password=password
    )
    try:
        history_message = build_history_message(result)
        pdf_path = result.pdf_path
        if not result.ok or pdf_path is None:
            note = (
                "PDF 未发送：文件超过体积上限"
                if result.status == "oversize"
                else "PDF 未发送：没有下载到任何页面"
            )
            info_text = build_info_text(result, note=note)
            nodes = build_forward_nodes(info_text, status_text=note)
            try:
                await _send_forward(
                    sender,
                    target_type,
                    target_id,
                    nodes,
                    history_message=history_message,
                )
            except Exception:
                logger.exception("[JM] 状态合并转发失败: book=%s", book_id)
                await _send_text(
                    sender,
                    target_type,
                    target_id,
                    f"{info_text}\n{note}",
                    history_message=history_message,
                )
            return f"JM{book_id} 已发送信息（{note}）"

        await _send_result(
            sender,
            target_type,
            target_id,
            book_id=book_id,
            info_text=build_info_text(result),
            password=password,
            pdf_path=pdf_path,
            history_message=history_message,
        )
        return (
            f"JM{book_id} 已发送合并转发与 PDF 文件"
            f"（{result.downloaded_chapters} 章 / {result.page_count} 页 / "
            f"{_format_size(result.size_bytes)}）"
        )
    finally:
        await cleanup_download_path(task_dir)
