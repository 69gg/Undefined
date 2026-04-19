"""arXiv 论文发送。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Literal

from Undefined.arxiv.client import get_paper_info
from Undefined.arxiv.downloader import cleanup_download_path, download_paper_pdf
from Undefined.arxiv.models import PaperInfo
from Undefined.arxiv.parser import normalize_arxiv_id

if TYPE_CHECKING:
    from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)

_INFLIGHT_LOCK = asyncio.Lock()
_INFLIGHT_SENDS: dict[tuple[str, int, str], asyncio.Future[str]] = {}

# Time-based dedup: maps (target_type, target_id, paper_id) → monotonic timestamp
_RECENT_SENDS: dict[tuple[str, int, str], float] = {}
_DEDUP_COOLDOWN_SECONDS: float = 3600.0  # 1 hour
_RECENT_SENDS_MAX_SIZE: int = 1000


def _cleanup_expired_recent_sends() -> None:
    """Remove expired entries from _RECENT_SENDS. Must be called under _INFLIGHT_LOCK."""
    now = time.monotonic()
    expired = [
        k for k, v in _RECENT_SENDS.items() if now - v >= _DEDUP_COOLDOWN_SECONDS
    ]
    for k in expired:
        del _RECENT_SENDS[k]


def _evict_oldest_recent_sends() -> None:
    """Evict oldest entries if _RECENT_SENDS exceeds max size. Must be called under _INFLIGHT_LOCK."""
    if len(_RECENT_SENDS) <= _RECENT_SENDS_MAX_SIZE:
        return
    sorted_keys = sorted(_RECENT_SENDS, key=lambda k: _RECENT_SENDS[k])
    excess = len(_RECENT_SENDS) - _RECENT_SENDS_MAX_SIZE
    for k in sorted_keys[:excess]:
        del _RECENT_SENDS[k]


def _build_abs_url(paper_id: str) -> str:
    return f"https://arxiv.org/abs/{paper_id}"


def _build_pdf_url(paper_id: str) -> str:
    return f"https://arxiv.org/pdf/{paper_id}.pdf"


def _minimal_paper_info(paper_id: str) -> PaperInfo:
    return PaperInfo(
        paper_id=paper_id,
        title=f"arXiv:{paper_id}",
        authors=(),
        summary="",
        published="",
        updated="",
        primary_category="",
        abs_url=_build_abs_url(paper_id),
        pdf_url=_build_pdf_url(paper_id),
    )


def _preview_authors(authors: tuple[str, ...], limit: int) -> str:
    if not authors:
        return ""
    if len(authors) <= limit:
        return "、".join(authors)
    return f"{'、'.join(authors[:limit])} 等{len(authors)}位作者"


def _preview_summary(summary: str, limit: int) -> str:
    normalized = " ".join(summary.split()).strip()
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _display_date(info: PaperInfo) -> str:
    source = info.published or info.updated
    if not source:
        return ""
    return source[:10]


def _build_info_message(
    info: PaperInfo,
    *,
    author_preview_limit: int,
    summary_preview_chars: int,
) -> str:
    lines: list[str] = [f"「{info.title or f'arXiv:{info.paper_id}'}」"]

    authors = _preview_authors(info.authors, author_preview_limit)
    if authors:
        lines.append(f"作者: {authors}")
    if info.primary_category:
        lines.append(f"分类: {info.primary_category}")
    display_date = _display_date(info)
    if display_date:
        lines.append(f"日期: {display_date}")

    summary_preview = _preview_summary(info.summary, summary_preview_chars)
    if summary_preview:
        lines.append("---")
        lines.append(summary_preview)

    lines.append("---")
    lines.append(info.abs_url)
    return "\n".join(lines)


async def _send_text_message(
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    message: str,
) -> None:
    if target_type == "group":
        await sender.send_group_message(target_id, message, auto_history=False)
    else:
        await sender.send_private_message(target_id, message, auto_history=False)


async def _send_file_message(
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    file_path: str,
    file_name: str,
) -> None:
    if target_type == "group":
        await sender.send_group_file(
            target_id, file_path, file_name, auto_history=False
        )
    else:
        await sender.send_private_file(
            target_id, file_path, file_name, auto_history=False
        )


async def _send_arxiv_paper_once(
    *,
    paper_id: str,
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    max_file_size: int,
    author_preview_limit: int,
    summary_preview_chars: int,
    context: dict[str, object] | None = None,
) -> str:
    info: PaperInfo
    metadata_ready = True
    try:
        info = await get_paper_info(paper_id, context=context)
    except Exception:
        metadata_ready = False
        info = _minimal_paper_info(paper_id)
        logger.exception("[arXiv] 获取论文元信息失败: paper=%s", paper_id)

    info_message = _build_info_message(
        info,
        author_preview_limit=author_preview_limit,
        summary_preview_chars=summary_preview_chars,
    )
    await _send_text_message(sender, target_type, target_id, info_message)

    download_result, task_dir = await download_paper_pdf(
        info,
        max_file_size_mb=max_file_size,
        context=context,
    )
    try:
        if download_result.path is None:
            if metadata_ready:
                return f"已发送论文信息：{info.paper_id}（未附带 PDF）"
            return f"已发送论文最小信息：{info.paper_id}（未附带 PDF）"

        try:
            await _send_file_message(
                sender,
                target_type,
                target_id,
                str(download_result.path.resolve()),
                download_result.path.name,
            )
            return f"已发送论文信息与 PDF：{info.paper_id}"
        except Exception:
            logger.exception(
                "[arXiv] PDF 上传失败，已跳过: paper=%s target=%s:%s",
                info.paper_id,
                target_type,
                target_id,
            )
            if metadata_ready:
                return f"已发送论文信息：{info.paper_id}（PDF 上传失败已跳过）"
            return f"已发送论文最小信息：{info.paper_id}（PDF 上传失败已跳过）"
    finally:
        await cleanup_download_path(task_dir)


async def send_arxiv_paper(
    *,
    paper_id: str,
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    max_file_size: int,
    author_preview_limit: int,
    summary_preview_chars: int,
    context: dict[str, object] | None = None,
) -> str:
    """发送 arXiv 论文信息并尽力附带 PDF。"""
    normalized = normalize_arxiv_id(paper_id)
    if normalized is None:
        return f"无法解析 arXiv 标识: {paper_id}"

    key = (target_type, int(target_id), normalized)
    created = False

    async with _INFLIGHT_LOCK:
        # Lazy cleanup of expired entries
        _cleanup_expired_recent_sends()

        # Check time-based dedup first
        recent_ts = _RECENT_SENDS.get(key)
        if (
            recent_ts is not None
            and (time.monotonic() - recent_ts) < _DEDUP_COOLDOWN_SECONDS
        ):
            logger.info(
                "[arXiv] 论文近期已发送，跳过: paper=%s target=%s:%s",
                normalized,
                target_type,
                target_id,
            )
            return f"论文 {normalized} 近期已发送过，已跳过"

        # Check inflight dedup
        future = _INFLIGHT_SENDS.get(key)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            _INFLIGHT_SENDS[key] = future
            created = True

    if not created:
        logger.info(
            "[arXiv] 复用在途发送任务: paper=%s target=%s:%s",
            normalized,
            target_type,
            target_id,
        )
        return await asyncio.shield(future)

    try:
        result = await _send_arxiv_paper_once(
            paper_id=normalized,
            sender=sender,
            target_type=target_type,
            target_id=target_id,
            max_file_size=max_file_size,
            author_preview_limit=author_preview_limit,
            summary_preview_chars=summary_preview_chars,
            context=context,
        )
    except Exception as exc:
        if not future.done():
            future.set_exception(exc)
        raise
    else:
        if not future.done():
            future.set_result(result)
        return result
    finally:
        async with _INFLIGHT_LOCK:
            current = _INFLIGHT_SENDS.get(key)
            if current is future:
                _INFLIGHT_SENDS.pop(key, None)
            # Record successful send time for dedup cooldown
            if future.done() and not future.cancelled() and future.exception() is None:
                _RECENT_SENDS[key] = time.monotonic()
                _evict_oldest_recent_sends()
