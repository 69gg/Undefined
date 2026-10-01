"""禁漫的合并转发发送与附件交付。

自动提取先发「本子信息 + 解密密码」两节点合并转发，随后把**一章一份加密 PDF 的
zip** 作为独立文件消息单独发出：转发节点里的文件在 QQ 客户端下载会失败，所以文件
不进转发。zip 本身不加密，密码在每个章节 PDF 内部，同一个密码适用于 zip 里所有
PDF。工具侧另有两条路：``format_jm_book_info`` 只输出详情（不下载），
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
    JmChapterArchive,
    JmPlainDownload,
    cleanup_download_path,
    download_book,
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


def _build_stats_line(result: JmChapterArchive) -> str:
    """「页数 | zip 大小」一行；还没有 zip 时只报页数。"""
    summary = f"页数: {result.page_count}"
    if result.size_bytes is None:
        return summary
    return f"{summary} | zip: {_format_size(result.size_bytes)}"


def build_info_text(result: JmChapterArchive, *, note: str = "") -> str:
    """信息节点（也是历史摘要的来源）的正文。"""
    book: Book = result.book
    lines = [f"「JM{book.book_id} {book.title or '未知标题'}」"]

    if book.authors:
        lines.append(f"作者: {', '.join(book.authors)}")
    lines.append(
        f"章节: {result.chapter_count} 章（本次出 {len(result.pdfs)} 份 PDF，每章一份）"
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

    lines.append(_build_stats_line(result))
    if result.skipped_chapters:
        # 少了哪几章必须写在用户能看到的地方，不能静默少发
        lines.append(
            f"{result.skipped_chapters} 章未打包（超过单章体积上限或没有可用页面）"
        )
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
    """密码节点正文。

    写明密码适用于 zip 内所有 PDF——用户先解压再逐个打开，不写清楚容易以为
    zip 本身要密码。
    """
    return f"zip 内所有 PDF 的解密密码（{len(password)} 位）：{password}"


def build_forward_nodes(
    info_text: str,
    *,
    password: str = "",
    status_text: str = "",
) -> list[dict[str, Any]]:
    """构建合并转发节点：信息 +（密码或状态）。

    文件不放进转发：转发节点里的文件在 QQ 客户端下载会失败，改由 :func:`_send_result`
    在转发之后单独发一条文件消息（2026-10-01 实测，同一份文件独立发送可正常下载）。
    """
    if not password:
        # 没有可发送的文件时用状态说明替代密码节点
        return [
            _node(info_text, name="本子信息"),
            _node(status_text or "文件未发送", name="状态"),
        ]
    return [
        _node(info_text, name="本子信息"),
        _node(build_password_text(password), name="解密密码"),
    ]


def build_history_message(result: JmChapterArchive) -> str:
    """历史摘要：只写可复述的信息，不含 PDF 密码。"""
    book = result.book
    lines = [
        f"[JM] 「{book.title or '未知标题'}」",
        f"车号: JM{book.book_id}",
        f"章节: {result.chapter_count} 章 | 页数: {result.page_count}",
    ]
    if result.ok:
        # 这条摘要随转发写入，此时文件还没上传：不能提前声称已发送。
        # 上传成功时 send_group_file 会自己补一条「[文件] … 」历史，失败时补提示。
        lines.append(
            f"zip: 加密 PDF（每章一份，共 {len(result.pdfs)} 份）随后单独发送"
            f"（{_format_size(result.size_bytes)}，密码见转发节点）"
        )
    else:
        lines.append("zip: 未发送")
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
    result: JmPlainDownload,
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

    result, task_dir = await download_book(book_id, config=config, password=None)
    try:
        if not isinstance(result, JmPlainDownload):
            # 没给密码时不可能拿到归档结果，这里只作类型收口
            return f"未能获取禁漫本子 PDF：内部状态异常｜JM{book_id}"
        if not result.ok or result.pdf_path is None:
            reason = (
                "PDF 超过单章体积上限"
                if result.status == "oversize"
                else "没有下载到任何页面"
            )
            return f"未能获取禁漫本子 PDF：{reason}｜JM{book_id}"
        pdf_path = result.pdf_path
        record = await attachment_registry.register_local_file(
            scope_key,
            pdf_path,
            kind="file",
            display_name=pdf_path.name,
            source_kind="jm_book",
            source_ref=build_album_url(result.book.book_id),
            segment_data={
                "book_id": result.book.book_id,
                "title": result.book.title,
                "page_count": result.page_count,
                "chapters": result.chapter_count,
            },
        )
        return _build_uid_message(result, uid=str(record.uid), file_name=pdf_path.name)
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


#: 转发投递结果的三态，既进日志也拼进返回值
_FORWARD_SENT = "已发送合并转发"
_FORWARD_REJECTED = "合并转发被拒，已改为普通消息发送信息与密码"
_FORWARD_UNCERTAIN = "合并转发投递结果未确认"


async def _send_result(
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    *,
    book_id: str,
    info_text: str,
    password: str,
    zip_path: Path,
    history_message: str,
) -> str:
    """发送「信息 + 密码」合并转发，再单独发送 zip 文件，返回可记录的真实投递状态。

    文件不进转发：转发节点里的文件在 QQ 客户端下载会失败，独立文件消息才下得动。
    转发被协议端**明确拒绝**时降级为两条普通消息（信息 / 密码）。投递结果未确认
    （``delivery_uncertain`` / ``file_transfer_error``）时不能降级重发信息与密码——
    转发可能已经送达；但文件是另一条消息、此前从未发出，必须继续单独发送，否则用户
    整本下载白跑。文件自身投递结果未确认时同样不重发，直接上抛调用方；普通失败时补
    一条写入历史的「文件上传失败」提示，转发投递未确认时提示不声称信息与密码已送达。
    """
    nodes = build_forward_nodes(info_text, password=password)
    forward_status = _FORWARD_SENT
    try:
        await _send_forward(
            sender, target_type, target_id, nodes, history_message=history_message
        )
    except Exception as exc:
        if _is_fatal_delivery_error(exc):
            logger.error(
                "[JM] 合并转发投递结果未确认，不重发信息与密码，继续单独发送 zip: book=%s",
                book_id,
            )
            forward_status = _FORWARD_UNCERTAIN
        else:
            logger.exception(
                "[JM] 合并转发失败，回退为普通消息发送信息与密码: book=%s", book_id
            )
            forward_status = _FORWARD_REJECTED
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
            sender, target_type, target_id, str(zip_path), str(zip_path.name)
        )
    except Exception as file_exc:
        if _is_fatal_delivery_error(file_exc):
            logger.error("[JM] 文件投递结果未确认，不重发: book=%s", book_id)
            raise
        logger.exception("[JM] zip 文件发送失败: book=%s", book_id)
        # 转发投递未确认时不能声称「信息与密码如上」——转发可能压根没送达
        notice = (
            "zip 上传失败，本次没有发送文件（合并转发投递结果未确认，信息与密码可能没有送达）。"
            if forward_status == _FORWARD_UNCERTAIN
            else "zip 上传失败，本次没有发送文件（信息与密码如上）。"
        )
        # 写进历史：转发摘要只说「随后发送」，真正发没发出去靠这条记录收口
        await _send_text(sender, target_type, target_id, notice)
        return f"{forward_status}，zip 文件发送失败"
    return f"{forward_status}，zip 文件已单独发送"


async def send_jm_book(
    book_id: str,
    *,
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    config: Any,
) -> str:
    """下载整本，发送「信息 + 密码」合并转发，再单独发送「一章一份 PDF」的 zip。"""
    password = generate_pdf_password()
    result, task_dir = await download_book(book_id, config=config, password=password)
    try:
        if not isinstance(result, JmChapterArchive):
            # 给了密码就必须拿到归档结果，这里只作类型收口
            logger.error("[JM] 下载结果不是章节归档: book=%s", book_id)
            return f"JM{book_id} 下载结果异常，未发送任何文件"

        history_message = build_history_message(result)
        if not result.ok:
            # 没有出任何章节 PDF：只发信息与状态两节点，不发密码与文件
            note = (
                "文件未发送：单章都超过体积上限"
                if result.status == "empty" and result.skipped_chapters
                else "文件未发送：没有下载到任何页面"
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

        zip_path = result.zip_path
        assert zip_path is not None  # result.ok 已经保证有 zip
        status = await _send_result(
            sender,
            target_type,
            target_id,
            book_id=book_id,
            info_text=build_info_text(result),
            password=password,
            zip_path=zip_path,
            history_message=history_message,
        )
        return (
            f"JM{book_id} {status}"
            f"（{len(result.pdfs)} 章 / {result.page_count} 页 / "
            f"{_format_size(result.size_bytes)}）"
        )
    finally:
        await cleanup_download_path(task_dir)
