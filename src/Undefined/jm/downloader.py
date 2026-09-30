"""禁漫本子下载：逐章取图，再合成一个加密 PDF。

jmcpy 的异步实现内部仍会同步执行图片解码与 PDF 合成（``_to_artifact`` /
``_finalize`` 直接在协程里跑），放在事件循环里会阻塞其它消息处理，因此这里用
同步 ``Client`` 配合 :func:`asyncio.to_thread`，线程里可以放心做 CPU 与磁盘工作。
代价是单次任务不可取消，由 jmcpy 自己的请求超时与多端点重试兜底。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Literal
import uuid

from jmcpy import Book, Client, ExportFormat, Settings
from jmcpy.imaging import write_pdf
from jmcpy.texts import sanitize_filename

from Undefined.jm.client import build_settings
from Undefined.utils.http_download import cleanup_download_dir
from Undefined.utils.paths import DOWNLOAD_CACHE_DIR, ensure_dir

logger = logging.getLogger(__name__)

_JM_DOWNLOAD_DIR = DOWNLOAD_CACHE_DIR / "jm"
_BOOK_ID_PREFIX = "JM"


@dataclass(frozen=True, slots=True)
class JmDownload:
    """一次本子下载的结果。"""

    #: ok=PDF 可用；oversize=超过体积上限；empty=没有下到任何页面
    status: Literal["ok", "oversize", "empty"]
    book: Book
    pdf_path: Path | None
    page_count: int
    size_bytes: int | None
    #: 本子声明的章节总数（单章本子为 1）
    chapter_count: int
    #: 本次实际下载并合并的章节数
    downloaded_chapters: int
    #: 下载失败的页面数（jmcpy 逐页收集，不打断整章）
    failed_pages: int

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.pdf_path is not None


def _chapter_ids(book: Book, *, max_chapters: int) -> list[int]:
    # 按本子内的章节序号排序，合出来的 PDF 与阅读顺序一致
    ordered = sorted(book.chapters, key=lambda chapter: int(chapter.order))
    chapter_ids = [int(chapter.chapter_id) for chapter in ordered]
    if not chapter_ids:
        # 单章本子的章节号就是车号
        chapter_ids = [int(book.book_id)]
    if max_chapters > 0:
        chapter_ids = chapter_ids[:max_chapters]
    return chapter_ids


def _pdf_file_name(book: Book) -> str:
    title = sanitize_filename(book.title) or "漫画"
    return f"{_BOOK_ID_PREFIX}{book.book_id} {title}.pdf"


def _limit_bytes(max_file_size_mb: int) -> int | None:
    return max_file_size_mb * 1024 * 1024 if max_file_size_mb > 0 else None


def _download_sync(
    book_id: str,
    task_dir: Path,
    *,
    password: str,
    settings: Settings,
    max_chapters: int,
    max_file_size_mb: int,
    pdf_dpi: float,
    image_quality: int,
) -> JmDownload:
    limit_bytes = _limit_bytes(max_file_size_mb)
    with Client(settings) as client:
        book = client.get_book(book_id)
        # 声明总数取本子自身的章节列表，不受 max_chapters 截断影响
        declared_chapters = len(book.chapters) or 1
        chapter_ids = _chapter_ids(book, max_chapters=max_chapters)
        pages: list[Path] = []
        failed_pages = 0
        downloaded_chapters = 0
        total_bytes = 0

        for index, chapter_id in enumerate(chapter_ids, start=1):
            chapter = client.get_chapter(chapter_id)
            if not len(chapter):
                logger.info(
                    "[JM] 章节没有图片，跳过: book=%s chapter=%s", book_id, chapter_id
                )
                continue
            # 每章独立的目录：同名章节复用同名目录时，overwrite=False 会拿旧图
            result = client.download(
                chapter,
                output=ExportFormat.PATH,
                dest=task_dir / f"c{index:03d}",
                concurrency=settings.concurrency,
                quality=image_quality,
            )
            pages.extend(result.paths)
            failed_pages += len(result.failures)
            downloaded_chapters += 1
            total_bytes += sum(item.size or 0 for item in result)
            if limit_bytes is not None and total_bytes > limit_bytes:
                logger.info(
                    "[JM] 图片总量超过体积上限，提前结束: book=%s bytes=%s limit=%sMB",
                    book_id,
                    total_bytes,
                    max_file_size_mb,
                )
                return JmDownload(
                    status="oversize",
                    book=book,
                    pdf_path=None,
                    page_count=len(pages),
                    size_bytes=total_bytes,
                    chapter_count=declared_chapters,
                    downloaded_chapters=downloaded_chapters,
                    failed_pages=failed_pages,
                )

        if not pages:
            return JmDownload(
                status="empty",
                book=book,
                pdf_path=None,
                page_count=0,
                size_bytes=None,
                chapter_count=declared_chapters,
                downloaded_chapters=downloaded_chapters,
                failed_pages=failed_pages,
            )

        pdf_path = write_pdf(
            pages,
            task_dir / _pdf_file_name(book),
            dpi=pdf_dpi,
            quality=image_quality,
            password=password,
        )
        size_bytes = pdf_path.stat().st_size
        status: Literal["ok", "oversize"] = "ok"
        if limit_bytes is not None and size_bytes > limit_bytes:
            logger.info(
                "[JM] PDF 超过体积上限: book=%s bytes=%s limit=%sMB",
                book_id,
                size_bytes,
                max_file_size_mb,
            )
            status = "oversize"
        return JmDownload(
            status=status,
            book=book,
            pdf_path=pdf_path,
            page_count=len(pages),
            size_bytes=size_bytes,
            chapter_count=declared_chapters,
            downloaded_chapters=downloaded_chapters,
            failed_pages=failed_pages,
        )


async def download_book_pdf(
    book_id: str,
    *,
    config: Any,
    password: str,
) -> tuple[JmDownload, Path]:
    """下载整本并合成加密 PDF，返回 ``(结果, 任务目录)``。

    调用方负责在发送完成后清理任务目录（``cleanup_download_path``）。
    """
    task_dir = ensure_dir(_JM_DOWNLOAD_DIR / uuid.uuid4().hex)
    result = await asyncio.to_thread(
        _download_sync,
        book_id,
        task_dir,
        password=password,
        settings=build_settings(config),
        max_chapters=int(getattr(config, "jm_max_chapters", 0)),
        max_file_size_mb=int(getattr(config, "jm_max_file_size", 100)),
        pdf_dpi=float(getattr(config, "jm_pdf_dpi", 150.0)),
        image_quality=int(getattr(config, "jm_image_quality", 95)),
    )
    return result, task_dir


async def cleanup_download_path(task_dir: Path) -> None:
    """清理本次任务的临时目录。"""
    await cleanup_download_dir(task_dir)
