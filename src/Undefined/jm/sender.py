"""禁漫的合并转发发送与附件交付。

自动提取一次发送三个节点：本子信息、PDF 解密密码、PDF 文件（本地合成后随转发上传）。
工具侧另有两条路：``format_jm_book_info`` 只输出详情（不下载），
``fetch_jm_book_attachment`` 下载整本并把**未加密** PDF 注册为附件 UID（不发送），
供 ``file_analysis_agent`` 继续解析。密码始终不会写进历史。
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
#: 公开站点车号链接（仅用于历史摘要，信息节点展示的是 ``JM<车号>``）
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
    if result.pdf_path is not None and result.size_bytes is not None:
        summary += f" | PDF: {_format_size(result.size_bytes)}"
    lines.append(summary)
    if result.failed_pages:
        lines.append(f"下载失败 {result.failed_pages} 页")
    if note:
        lines.append(note)

    description = _preview(book.description)
    if description and description != book.title:
        lines.extend(["---", description])

    # 末尾给可复制的车号而不是站点链接：QQ 里点不开，车号还能直接再触发一次提取
    lines.extend(["---", f"JM{book.book_id}"])
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

    PDF 是本地合成好的真实文件，随转发一起上传：群聊下 NapCat 会把它作为群文件上传
    （``isGroupFile``、``busid=102``，元素里带 ``fileId`` / ``fileMd5`` / ``fileSha1``），
    因此同一个 PDF 也会出现在群文件列表里，转发节点里的文件可以直接下载
    （2026-10-01 用 14MB PDF 实测通过）。文件只发一次，不另外发独立文件消息。
    """
    if pdf_path is None:
        # 没有可发送的 PDF 时用状态说明替代密码与文件节点
        return [
            _node(info_text, name="本子信息"),
            _node(status_text or "PDF 未发送", name="状态"),
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


def format_jm_book_info(book: Book) -> str:
    """本子详情的文本形式（工具 ``output_mode=info`` 用，不下载任何图片）。"""
    lines = [f"「JM{book.book_id} {book.title or '未知标题'}」"]
    if book.authors:
        lines.append(f"作者: {', '.join(book.authors)}")
    lines.append(f"章节: {len(book.chapters) or 1} 章")
    if book.tags:
        lines.append(f"标签: {'、'.join(book.tags[:_MAX_TAGS])}")
    stats: list[str] = []
    if book.views is not None:
        stats.append(f"观看 {book.views}")
    if book.likes is not None:
        stats.append(f"点赞 {book.likes}")
    if book.comment_count is not None:
        stats.append(f"评论 {book.comment_count}")
    if stats:
        lines.append(" | ".join(stats))

    description = _preview(book.description)
    if description and description != book.title:
        lines.extend(["---", description])

    lines.extend(["---", f"车号: JM{book.book_id}", build_album_url(book.book_id)])
    return "\n".join(lines)


def _build_uid_message(
    result: JmDownload,
    *,
    uid: str,
    file_name: str,
) -> str:
    book = result.book
    lines = [
        f"已获取禁漫本子 PDF：「{book.title or '未知标题'}」",
        f"车号: JM{book.book_id}",
        f"章节: {result.chapter_count} 章 | 页数: {result.page_count}",
        f'PDF: <attachment uid="{uid}"/>',
    ]
    if file_name:
        lines.append(f"文件名: {file_name}")
    if result.size_bytes is not None:
        lines.append(f"大小: {_format_size(result.size_bytes)}")
    lines.append("说明: 该 PDF 未加密，可直接解析")
    lines.append(build_album_url(book.book_id))
    return "\n".join(lines)


async def fetch_jm_book_attachment(
    *,
    book_id: str,
    attachment_registry: Any,
    scope_key: str,
    config: Any,
) -> str:
    """下载整本并注册为附件 UID（工具 ``output_mode=uid``，不发送消息）。

    输出**未加密** PDF：这条路的用途是把文件交给 ``file_analysis_agent`` 解析，
    加密会让 ``extract_pdf`` / ``describe_pdf_page`` 打不开。
    """
    if attachment_registry is None:
        return "缺少必要的运行时组件（attachment_registry）"
    if not str(scope_key or "").strip():
        return "无法确定附件作用域，不能注册禁漫本子 PDF"

    result, task_dir = await download_book_pdf(book_id, config=config, password=None)
    try:
        if not result.ok or result.pdf_path is None:
            reason = (
                f"PDF 超过体积上限（已下载 {result.page_count} 页）"
                if result.status == "oversize"
                else "没有下载到任何页面"
            )
            return f"未能获取禁漫本子 PDF：{reason}｜JM{book_id}"
        record = await attachment_registry.register_local_file(
            scope_key,
            result.pdf_path,
            kind="file",
            display_name=result.pdf_path.name,
            source_kind="jm_book",
            source_ref=build_album_url(result.book.book_id),
            segment_data={
                "book_id": result.book.book_id,
                "title": result.book.title,
                "page_count": result.page_count,
                "chapters": result.chapter_count,
            },
        )
        return _build_uid_message(
            result, uid=str(record.uid), file_name=result.pdf_path.name
        )
    finally:
        await cleanup_download_path(task_dir)


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
    auto_history: bool = True,
) -> None:
    if target_type == "group":
        await sender.send_group_message(
            target_id,
            message,
            auto_history,
            history_message=history_message,
        )
    else:
        await sender.send_private_message(
            target_id,
            message,
            auto_history,
            history_message=history_message,
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


def _is_fatal_delivery_error(exc: BaseException) -> bool:
    """投递结果未确认 / 文件传输错误：绝不能降级重发（仓库约定）。

    判据与 ``bilibili/opus_sender.py`` 的 ``_FATAL_ERROR_FLAGS`` 一致：这类异常
    可能已经送达，换个 action 再发一次会造成真实重复投递。
    """
    return bool(getattr(exc, "delivery_uncertain", False)) or bool(
        getattr(exc, "file_transfer_error", False)
    )


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
) -> str:
    """发送「信息 + 密码 + PDF」三节点合并转发，返回可记录的真实投递状态。

    文件只在转发里，不再额外发独立文件消息。群聊下这次上传会让 PDF 同时出现在群的
    文件列表里（``busid=102``），那是 QQ 自己的行为，不是我们单独发出去的。
    投递未确认 / 文件传输错误一律上抛，只有协议端**明确拒绝**才降级重发；降级时
    文件没有别的入口，必须补发一条独立文件消息，否则用户拿不到 PDF。
    """
    nodes = build_forward_nodes(info_text, pdf_path=pdf_path, password=password)
    try:
        await _send_forward(
            sender, target_type, target_id, nodes, history_message=history_message
        )
    except Exception as exc:
        if _is_fatal_delivery_error(exc):
            logger.error("[JM] 合并转发投递结果未确认，不重发: book=%s", book_id)
            raise
        logger.exception("[JM] 合并转发失败，回退为普通消息 + 文件: book=%s", book_id)
        # 历史里不留密码：历史摘要与用户可见正文分开；密码消息只记「已单独发送」
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
            history_message="[JM] PDF 解密密码已单独发送",
        )
        try:
            await _send_file(
                sender, target_type, target_id, str(pdf_path), str(pdf_path.name)
            )
        except Exception as file_exc:
            if _is_fatal_delivery_error(file_exc):
                logger.error("[JM] 文件投递结果未确认，不重发: book=%s", book_id)
                raise
            logger.exception("[JM] 降级后的 PDF 文件发送失败: book=%s", book_id)
            await _send_text(
                sender,
                target_type,
                target_id,
                "PDF 上传失败，本次没有发送文件（信息与密码如上）。",
                auto_history=False,
            )
            return "合并转发与 PDF 文件均发送失败，已改为普通消息发送信息与密码"
        return "合并转发被拒，已改为普通消息发送信息与密码，并补发独立 PDF 文件"
    return "已发送合并转发与 PDF 文件"


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
            except Exception as exc:
                if _is_fatal_delivery_error(exc):
                    logger.error(
                        "[JM] 状态转发投递结果未确认，不重发: book=%s", book_id
                    )
                    raise
                logger.exception("[JM] 状态合并转发失败: book=%s", book_id)
                await _send_text(
                    sender,
                    target_type,
                    target_id,
                    f"{info_text}\n{note}",
                    history_message=history_message,
                )
            return f"JM{book_id} 已发送信息（{note}）"

        status = await _send_result(
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
            f"JM{book_id} {status}"
            f"（{result.downloaded_chapters} 章 / {result.page_count} 页 / "
            f"{_format_size(result.size_bytes)}）"
        )
    finally:
        await cleanup_download_path(task_dir)
