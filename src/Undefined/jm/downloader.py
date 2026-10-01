"""禁漫本子下载：逐章取图，再合成一个加密 PDF。

jmcpy 的异步实现内部仍会同步执行图片解码与 PDF 合成（``_to_artifact`` /
``_finalize`` 直接在协程里跑），放在事件循环里会阻塞其它消息处理，因此这里用
同步 ``Client`` 配合 :func:`asyncio.to_thread`，线程里可以放心做 CPU 与磁盘工作。
代价是单次任务不可取消，由 jmcpy 自己的请求超时与多端点重试兜底。

合成不走 ``jmcpy.imaging.write_pdf``，而是自己用 PyMuPDF 逐页写入，原因是：

* 要把**多个章节**合进同一个 PDF——jmcpy 的下载 API 只能一章一个 PDF；
* 每页只编码一次：``download(output=PATH)`` 会先把解扰后的图重新编码一次
  （WebP/JPEG），合成时再编码第二次；这里用 ``decode=False`` 取服务端原始字节
  （无损落盘），自己解扰后只编码一次 JPEG（4:4:4，漫画的彩色描边在 4:2:0 下
  会发虚）；
* 页尺寸由我们统一控制（页宽 = 像素宽 ÷ dpi × 72）。

jmcpy ≤0.1.1 的 ``write_pdf`` 还会让追加页退回默认 72 DPI（同一份 PDF 里第一页
5.6in 宽、其余页 11.7in 宽），该问题已在 0.1.2 修复；这里保留自建组装是为了上面
三点，与那个 bug 无关。
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import functools
import io
import logging
import shutil
from pathlib import Path
from typing import Any, Literal
import uuid

import fitz
from jmcpy import Book, Client, ExportFormat, Settings
from jmcpy.imaging import block_count, descramble, load_image
from jmcpy.models import Picture
from jmcpy.texts import sanitize_filename
from PIL import Image

from Undefined.jm.client import build_settings
from Undefined.utils.http_download import cleanup_download_dir
from Undefined.utils.paths import DOWNLOAD_CACHE_DIR, ensure_dir

logger = logging.getLogger(__name__)

_JM_DOWNLOAD_DIR = DOWNLOAD_CACHE_DIR / "jm"
_BOOK_ID_PREFIX = "JM"
#: 整本下载是分钟级、不可取消的任务：用专用线程池，避免占满事件循环默认执行器
#: （默认池同时承担 utils/io 的磁盘写入），同时把并发本子数限制在这个数量。
_MAX_CONCURRENT_DOWNLOADS = 2
_DOWNLOAD_POOL = ThreadPoolExecutor(
    max_workers=_MAX_CONCURRENT_DOWNLOADS, thread_name_prefix="jm-download"
)
#: JPEG 色度不做下采样：漫画的彩色描边与文字在 4:2:0 下会发虚
_JPEG_SUBSAMPLING = 0
#: PDF 页物理尺寸 = 像素 ÷ DPI，所有页统一用这个 DPI
_POINTS_PER_INCH = 72.0


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


def _load_page(page_path: Path, picture: Picture) -> Image.Image:
    """读取一页原图并按需解扰（服务端把竖直分块打乱，块数由章节号与文件名决定）。"""
    image = load_image(page_path.read_bytes())
    # 动图不做分块还原（与 jmcpy 的 UNDECODED_SUFFIXES 语义一致）
    blocks = block_count(picture.scramble_id, picture.chapter_id, picture.filename)
    if blocks > 1 and not picture.is_animated:
        image = descramble(image, blocks)
    # PDF 只稳定支持这几种颜色模式，其余统一转 RGB
    return image if image.mode == "RGB" else image.convert("RGB")


@dataclass(frozen=True, slots=True)
class _PdfBuild:
    """PDF 组装结果。"""

    status: Literal["ok", "oversize", "empty"]
    #: ``oversize`` / ``empty`` 时为 ``None``
    path: Path | None
    page_count: int
    #: 成功写入的页在 PDF 里的编码字节数（``max_file_size`` 按它判定）
    encoded_bytes: int
    #: 组装阶段因解码失败被跳过的页数
    failed_pages: int


def _write_pdf(
    pages: list[tuple[Path, Picture]],
    output: Path,
    *,
    dpi: float,
    quality: int,
    password: str | None,
    limit_bytes: int | None,
) -> _PdfBuild:
    """把页面按顺序合成一个 PDF（页尺寸统一、每页只编码一次）。

    ``password`` 为 ``None`` 时不加密——附件 UID 模式要交给 PDF 解析，加密会让
    ``extract_pdf`` / ``describe_pdf_page`` 打不开。单页解码失败只跳过该页并计数，
    不整本放弃；累计编码字节超过 ``limit_bytes`` 时提前中止（此时 PDF 未落盘）。
    """
    document = fitz.open()
    page_count = 0
    encoded_bytes = 0
    failed_pages = 0
    try:
        for page_path, picture in pages:
            try:
                image = _load_page(page_path, picture)
            except Exception:
                failed_pages += 1
                logger.warning(
                    "[JM] 跳过无法解码的页面: %s", page_path.name, exc_info=True
                )
                continue
            width, height = image.size
            page = document.new_page(
                width=width * _POINTS_PER_INCH / dpi,
                height=height * _POINTS_PER_INCH / dpi,
            )
            buffer = io.BytesIO()
            image.save(
                buffer,
                format="JPEG",
                quality=quality,
                subsampling=_JPEG_SUBSAMPLING,
            )
            data = buffer.getvalue()
            encoded_bytes += len(data)
            if limit_bytes is not None and encoded_bytes > limit_bytes:
                logger.info(
                    "[JM] PDF 编码后体积超过上限，提前中止: bytes=%s limit=%s",
                    encoded_bytes,
                    limit_bytes,
                )
                return _PdfBuild(
                    "oversize", None, page_count, encoded_bytes, failed_pages
                )
            # MuPDF 对 JPEG 流做 DCT 直通：上面这一次编码就是 PDF 里的最终数据
            page.insert_image(page.rect, stream=data)
            page_count += 1

        if page_count == 0:
            return _PdfBuild("empty", None, 0, encoded_bytes, failed_pages)

        if password is None:
            document.save(str(output), garbage=3, deflate=True)
        else:
            document.save(
                str(output),
                encryption=fitz.PDF_ENCRYPT_AES_256,
                user_pw=password,
                owner_pw=password,
                garbage=3,
                deflate=True,
            )
    finally:
        document.close()
    return _PdfBuild("ok", output, page_count, encoded_bytes, failed_pages)


def _download_sync(
    book_id: str,
    task_dir: Path,
    *,
    password: str | None,
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
        pages: list[tuple[Path, Picture]] = []
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
            # 每章独立的目录：同名章节复用同名目录时，overwrite=False 会拿旧图。
            # decode=False 取服务端原始字节（无损），解扰与编码在写 PDF 时做一次。
            result = client.download(
                chapter,
                output=ExportFormat.PATH,
                dest=task_dir / f"c{index:03d}",
                decode=False,
                concurrency=settings.concurrency,
            )
            for item in result:
                if item.path is not None:
                    pages.append((item.path, item.picture))
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

        build = _write_pdf(
            pages,
            task_dir / _pdf_file_name(book),
            dpi=pdf_dpi,
            quality=image_quality,
            password=password,
            limit_bytes=limit_bytes,
        )
        failed_pages += build.failed_pages
        if build.status != "ok" or build.path is None:
            logger.info(
                "[JM] PDF 未生成: book=%s status=%s pages=%s bytes=%s",
                book_id,
                build.status,
                build.page_count,
                build.encoded_bytes,
            )
            return JmDownload(
                status=build.status,
                book=book,
                pdf_path=None,
                page_count=build.page_count,
                size_bytes=build.encoded_bytes or None,
                chapter_count=declared_chapters,
                downloaded_chapters=downloaded_chapters,
                failed_pages=failed_pages,
            )

        return JmDownload(
            status="ok",
            book=book,
            pdf_path=build.path,
            page_count=build.page_count,
            size_bytes=build.path.stat().st_size,
            chapter_count=declared_chapters,
            downloaded_chapters=downloaded_chapters,
            failed_pages=failed_pages,
        )


def _fetch_book_sync(book_id: str, settings: Settings) -> Book:
    with Client(settings) as client:
        return client.get_book(book_id)


async def fetch_book(book_id: str, *, config: Any) -> Book:
    """只取本子详情，不下载任何图片（线程里跑，不阻塞事件循环）。"""
    return await asyncio.to_thread(_fetch_book_sync, book_id, build_settings(config))


async def download_book_pdf(
    book_id: str,
    *,
    config: Any,
    password: str | None = None,
) -> tuple[JmDownload, Path]:
    """下载整本并合成 PDF，返回 ``(结果, 任务目录)``。

    ``password`` 给出时用 AES-256 加密（自动提取用），``None`` 时输出未加密 PDF
    （附件 UID 模式用，便于 PDF 解析）。调用方负责在发送或登记完成后清理任务目录
    （``cleanup_download_path``）；本函数抛异常或被取消时自己清理，不留残留目录。
    """
    task_dir = ensure_dir(_JM_DOWNLOAD_DIR / uuid.uuid4().hex)
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(
        _DOWNLOAD_POOL,
        functools.partial(
            _download_sync,
            book_id,
            task_dir,
            password=password,
            settings=build_settings(config),
            max_chapters=int(getattr(config, "jm_max_chapters", 0)),
            max_file_size_mb=int(getattr(config, "jm_max_file_size", 100)),
            pdf_dpi=float(getattr(config, "jm_pdf_dpi", 150.0)),
            image_quality=int(getattr(config, "jm_image_quality", 95)),
        ),
    )
    try:
        # shield：协程被取消时不要把线程一起取消——同步下载停不下来，强行删目录
        # 只会被后续写入重新创建，所以等它跑完再清理
        result = await asyncio.shield(future)
    except BaseException:
        if future.done():
            # 异常路径下调用方拿不到 task_dir，必须在这里清掉已下载的原图
            await cleanup_download_dir(task_dir)
        else:
            _cleanup_when_finished(future, task_dir, loop=loop)
        raise
    return result, task_dir


def _remove_dir_now(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _cleanup_when_finished(
    future: "asyncio.Future[JmDownload]",
    task_dir: Path,
    *,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """线程仍在写盘时，等它结束后再删任务目录（取消/超时路径）。"""

    def _on_done(_future: "asyncio.Future[JmDownload]") -> None:
        try:
            loop.run_in_executor(None, _remove_dir_now, task_dir)
        except RuntimeError:
            # 事件循环已关闭：退化为同步删除，避免残留原图或未加密 PDF
            _remove_dir_now(task_dir)

    future.add_done_callback(_on_done)


async def cleanup_download_path(task_dir: Path) -> None:
    """清理本次任务的临时目录。"""
    await cleanup_download_dir(task_dir)
