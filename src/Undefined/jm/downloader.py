"""禁漫本子下载：逐章取图，一章合成一份加密 PDF，再打包成一个无密码 zip。

合成不走 ``jmcpy.imaging.write_pdf``，而是自己用 PyMuPDF 逐页写入，原因是：

* 每章一份 PDF 再打包成 zip——jmcpy 的下载 API 虽然也是一章一个 PDF，但它产出的
  是「解码 + 重编码」后的成品，页尺寸由它决定；这里要自己控制页尺寸与编码次数；
* 每页只编码一次：``download(output=PATH)`` 会先把解扰后的图重新编码一次
  （WebP/JPEG），合成时再编码第二次；这里用 ``decode=False`` 取服务端原始字节
  （无损落盘），自己解扰后只编码一次 JPEG（4:4:4，漫画的彩色描边在 4:2:0 下
  会发虚）；
* 页尺寸由我们统一控制（页宽 = 像素宽 ÷ dpi × 72）。

jmcpy ≤0.1.1 的 ``write_pdf`` 还会让追加页退回默认 72 DPI（同一份 PDF 里第一页
5.6in 宽、其余页 11.7in 宽），该问题已在 0.1.2 修复；这里保留自建组装是为了上面
三点，与那个 bug 无关。

zip 用标准库 :mod:`zipfile` 写成、**不加密**：每个章节 PDF 各自用同一个密码做
AES-256 加密，用户解压后逐份输入同一个密码即可。``[jm].chapter_max_file_size``
按**单章 PDF** 判定，超限的那一章跳过（不再中止整本），其余章节照常打包。

jmcpy 的异步实现内部仍会同步执行图片解码与 PDF 合成（``_to_artifact`` /
``_finalize`` 直接在协程里跑），放在事件循环里会阻塞其它消息处理，因此这里用
同步 ``Client`` 配合 :func:`asyncio.to_thread`，线程里可以放心做 CPU 与磁盘工作。
代价是单次任务不可取消，由 jmcpy 自己的请求超时与多端点重试兜底。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import asyncio
import functools
import io
import logging
import shutil
from pathlib import Path
from typing import Any, Literal, TypeAlias
import uuid
import zipfile

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
#: zip 条目名与磁盘上的章节 PDF 同名：章节序号补零，解压后按文件名就是阅读顺序
_CHAPTER_INDEX_DIGITS = 3
#: 章节 PDF 在 zip 里的扩展名
_PDF_SUFFIX = ".pdf"
#: 交付物 zip 的扩展名
_ZIP_SUFFIX = ".zip"

#: 打包结果：ok=全部章节成 PDF；partial=有章节被跳过但仍出了 zip；empty=一份都没有
JmArchiveStatus: TypeAlias = Literal["ok", "partial", "empty"]
#: 单份 PDF 结果：ok=可用；oversize=超过单章体积上限；empty=没有可写入的页面
JmPlainStatus: TypeAlias = Literal["ok", "oversize", "empty"]


@dataclass(frozen=True, slots=True)
class ChapterPdfInfo:
    """一份章节 PDF 的基本信息（体积取 zip 内的字节数）。"""

    order: int
    chapter_id: int
    title: str
    page_count: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class JmChapterArchive:
    """自动提取路径的下载结果：每章一份加密 PDF + 一个无密码 zip。"""

    status: JmArchiveStatus
    book: Book
    #: 没有可打包的章节时为 ``None``
    zip_path: Path | None
    #: zip 大小；``None`` 表示还没有 zip
    size_bytes: int | None
    #: 实际写进 zip 的页数合计
    page_count: int
    #: 本子声明的章节总数（单章本子为 1）
    chapter_count: int
    #: 成功下载的章节来源数（含被体积上限跳过、最终没进 zip 的章节）
    downloaded_chapters: int
    #: 下载失败的页面数（jmcpy 逐页收集，不打断整章）
    failed_pages: int
    #: 没有进 zip 的章节数（超过单章体积上限、PDF 为空或该章页面全部解码失败）
    skipped_chapters: int
    #: 已进 zip 的章节，按阅读顺序
    pdfs: tuple[ChapterPdfInfo, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return self.status != "empty" and self.zip_path is not None


@dataclass(frozen=True, slots=True)
class JmPlainDownload:
    """``jm_book`` 工具 ``uid`` 路径的结果：一份**未加密** PDF（供 PDF 解析工具打开）。"""

    status: JmPlainStatus
    book: Book
    #: ``oversize`` / ``empty`` 时为 ``None``
    pdf_path: Path | None
    page_count: int
    size_bytes: int | None
    #: 本子声明的章节总数（单章本子为 1）
    chapter_count: int
    #: 本次实际下载并合并的章节数
    downloaded_chapters: int
    failed_pages: int

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.pdf_path is not None


#: 两种下载结果：自动提取拿 :class:`JmChapterArchive`，``uid`` 路径拿 :class:`JmPlainDownload`
JmDownload: TypeAlias = JmChapterArchive | JmPlainDownload


def _ordered_chapters(book: Book, *, max_chapters: int) -> list[tuple[int, int, str]]:
    """按本子内的章节序号排出 ``(章节号, 章节序号, 章节标题)``，顺序就是阅读顺序。

    序号取自 ``ChapterBrief.order`` 而不是「第几次下载」：服务端没给图的章节会被跳过，
    按下载次序编号会让后面的章节缺号。单章本子的章节号就是车号，序号是 1。
    """
    ordered = sorted(book.chapters, key=lambda chapter: int(chapter.order))
    chapters = [
        (int(chapter.chapter_id), int(chapter.order), str(chapter.title or ""))
        for chapter in ordered
    ]
    if not chapters:
        chapters = [(int(book.book_id), 1, "")]
    if max_chapters > 0:
        chapters = chapters[:max_chapters]
    return chapters


def _book_file_name(book: Book, suffix: str) -> str:
    """交付物文件名：``JM<车号> <净化后的标题><后缀>``。"""
    title = sanitize_filename(book.title) or "漫画"
    return f"{_BOOK_ID_PREFIX}{book.book_id} {title}{suffix}"


def _chapter_pdf_name(stem: str, title: str) -> str:
    """章节 PDF 名：``<产物名主体>[ <章节标题>].pdf``。

    ``stem`` 由 :func:`_download_archive_sync` 内的 ``artifact_stem`` 生成，已经保证
    同一次下载内唯一。章节标题写在文件名里便于挑选章节；服务端没给标题时只留序号。
    """
    chapter_title = sanitize_filename(title)
    return (
        f"{stem} {chapter_title}{_PDF_SUFFIX}"
        if chapter_title
        else f"{stem}{_PDF_SUFFIX}"
    )


def _chapter_limit_bytes(max_file_size_mb: int) -> int | None:
    """单章 PDF 上限；``None`` 表示不限。"""
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
    #: 成功写入的页在 PDF 里的编码字节数（单章上限按它判定）
    encoded_bytes: int
    #: 组装阶段因解码失败被跳过的页数
    failed_pages: int


def _write_pdf(
    pages: Sequence[tuple[Path, Picture]],
    output: Path,
    *,
    dpi: float,
    quality: int,
    password: str | None,
    limit_bytes: int | None,
) -> _PdfBuild:
    """把一章的页面按顺序合成一份 PDF（页尺寸统一、每页只编码一次）。

    ``password`` 为 ``None`` 时不加密——附件 UID 模式要交给 PDF 解析，加密会让
    ``extract_pdf`` / ``describe_page`` 打不开。单页解码失败只跳过该页并计数，
    不整章放弃；累计编码字节超过 ``limit_bytes`` 时提前中止（此时 PDF 未落盘），
    由调用方决定是跳过这一章还是放弃整本。
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
                    "[JM] 单章 PDF 编码后体积超过上限，跳过该章: bytes=%s limit=%s",
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


def _write_zip(parts: Sequence[tuple[str, bytes]], output: Path) -> int:
    """把各章节 PDF 写成无密码 zip，返回 zip 字节数。

    zip 本身不加密：密码在每个章节 PDF 内部，用户解压后逐份输入同一个密码。
    """
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts:
            archive.writestr(name, data)
    return output.stat().st_size


@dataclass(frozen=True, slots=True)
class _ChapterPdf:
    """一份刚写好的章节 PDF：zip 条目名 + 字节 + 便于回报的元信息。"""

    name: str
    data: bytes
    info: ChapterPdfInfo


def _download_archive_sync(
    book_id: str,
    task_dir: Path,
    *,
    password: str,
    settings: Settings,
    max_chapters: int,
    chapter_max_file_size_mb: int,
    pdf_dpi: float,
    image_quality: int,
) -> JmChapterArchive:
    """逐章下载并各出一份加密 PDF，最后打包成无密码 zip。"""
    limit_bytes = _chapter_limit_bytes(chapter_max_file_size_mb)
    built: list[_ChapterPdf] = []
    used_orders: set[int] = set()
    downloaded_chapters = 0
    skipped_chapters = 0
    failed_pages = 0
    page_count = 0

    def artifact_index(chapter_order: int, local_index: int, chapter_id: int) -> str:
        """章节产物的序号（补零字符串），用于下载目录名与 zip 条目名。

        优先用服务端章节序号（与阅读顺序一致）；服务端返回重复序号（异常数据）时退回
        本次下载的局部序号，否则两条章节会撞同一个下载目录与图片文件名
        （``overwrite=False`` 会拿旧图），也会撞同一个 zip 条目名而丢掉一份 PDF。
        """
        index = chapter_order
        if index in used_orders:
            index = local_index
            logger.warning(
                "[JM] 服务端返回重复章节序号，改用局部序号避免覆盖: book=%s chapter=%s order=%s → %s",
                book_id,
                chapter_id,
                chapter_order,
                index,
            )
        used_orders.add(index)
        return f"{index:0{_CHAPTER_INDEX_DIGITS}d}"

    with Client(settings) as client:
        book = client.get_book(book_id)
        # 声明总数取本子自身的章节列表，不受 max_chapters 截断影响
        declared_chapters = len(book.chapters) or 1
        chapters = _ordered_chapters(book, max_chapters=max_chapters)

        for local_index, (chapter_id, chapter_order, chapter_title) in enumerate(
            chapters, start=1
        ):
            chapter = client.get_chapter(chapter_id)
            if not len(chapter):
                logger.info(
                    "[JM] 章节没有图片，跳过: book=%s chapter=%s", book_id, chapter_id
                )
                continue
            index = artifact_index(chapter_order, local_index, chapter_id)
            # 每章独立的目录：同名目录复用同名目录时，overwrite=False 会拿旧图。
            # decode=False 取服务端原始字节（无损），解扰与编码在写 PDF 时做一次。
            result = client.download(
                chapter,
                output=ExportFormat.PATH,
                dest=task_dir / f"c{index}",
                decode=False,
                concurrency=settings.concurrency,
            )
            pages = [
                (item.path, item.picture) for item in result if item.path is not None
            ]
            failed_pages += len(result.failures)
            downloaded_chapters += 1

            if not pages:
                # 这一章的页面全部下载失败：计一次跳过，继续下一章
                skipped_chapters += 1
                logger.warning(
                    "[JM] 章节没有可用页面，跳过: book=%s chapter=%s",
                    book_id,
                    chapter_id,
                )
                continue

            output = task_dir / _chapter_pdf_name(
                f"{_BOOK_ID_PREFIX}{book.book_id} {index}", chapter_title
            )
            build = _write_pdf(
                pages,
                output,
                dpi=pdf_dpi,
                quality=image_quality,
                password=password,
                limit_bytes=limit_bytes,
            )
            failed_pages += build.failed_pages
            if build.status != "ok" or build.path is None:
                # 单章超限/无可用页面只丢这一章；整本因此仍可能发出 zip
                skipped_chapters += 1
                logger.info(
                    "[JM] 章节 PDF 未生成，跳过该章: book=%s chapter=%s status=%s pages=%s bytes=%s",
                    book_id,
                    chapter_id,
                    build.status,
                    build.page_count,
                    build.encoded_bytes,
                )
                continue

            data = build.path.read_bytes()
            built.append(
                _ChapterPdf(
                    name=build.path.name,
                    data=data,
                    info=ChapterPdfInfo(
                        order=chapter_order,
                        chapter_id=chapter_id,
                        title=chapter_title,
                        page_count=build.page_count,
                        size_bytes=len(data),
                    ),
                )
            )
            page_count += build.page_count

        if not built:
            return JmChapterArchive(
                status="empty",
                book=book,
                zip_path=None,
                size_bytes=None,
                page_count=0,
                chapter_count=declared_chapters,
                downloaded_chapters=downloaded_chapters,
                failed_pages=failed_pages,
                skipped_chapters=skipped_chapters,
            )

        zip_path = task_dir / _book_file_name(book, _ZIP_SUFFIX)
        zip_bytes = _write_zip([(item.name, item.data) for item in built], zip_path)
        # 章节 PDF 已进 zip，删掉散落副本，任务目录里只留最终交付物
        for item in built:
            (task_dir / item.name).unlink(missing_ok=True)

        return JmChapterArchive(
            status="partial" if skipped_chapters else "ok",
            book=book,
            zip_path=zip_path,
            size_bytes=zip_bytes,
            page_count=page_count,
            chapter_count=declared_chapters,
            downloaded_chapters=downloaded_chapters,
            failed_pages=failed_pages,
            skipped_chapters=skipped_chapters,
            pdfs=tuple(item.info for item in built),
        )


def _download_plain_sync(
    book_id: str,
    task_dir: Path,
    *,
    settings: Settings,
    max_chapters: int,
    chapter_max_file_size_mb: int,
    pdf_dpi: float,
    image_quality: int,
) -> JmPlainDownload:
    """把各章页面合并成**一份未加密** PDF（``jm_book`` 的 ``uid`` 路径）。"""
    limit_bytes = _chapter_limit_bytes(chapter_max_file_size_mb)
    with Client(settings) as client:
        book = client.get_book(book_id)
        # 声明总数取本子自身的章节列表，不受 max_chapters 截断影响
        declared_chapters = len(book.chapters) or 1
        chapters = _ordered_chapters(book, max_chapters=max_chapters)
        pages: list[tuple[Path, Picture]] = []
        failed_pages = 0
        downloaded_chapters = 0

        for chapter_id, chapter_order, _title in chapters:
            chapter = client.get_chapter(chapter_id)
            if not len(chapter):
                logger.info(
                    "[JM] 章节没有图片，跳过: book=%s chapter=%s", book_id, chapter_id
                )
                continue
            result = client.download(
                chapter,
                output=ExportFormat.PATH,
                dest=task_dir / f"c{chapter_order:0{_CHAPTER_INDEX_DIGITS}d}",
                decode=False,
                concurrency=settings.concurrency,
            )
            pages.extend(
                (item.path, item.picture) for item in result if item.path is not None
            )
            failed_pages += len(result.failures)
            downloaded_chapters += 1

        if not pages:
            return JmPlainDownload(
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
            task_dir / _book_file_name(book, _PDF_SUFFIX),
            dpi=pdf_dpi,
            quality=image_quality,
            password=None,
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
            return JmPlainDownload(
                status=build.status,
                book=book,
                pdf_path=None,
                page_count=build.page_count,
                size_bytes=build.encoded_bytes or None,
                chapter_count=declared_chapters,
                downloaded_chapters=downloaded_chapters,
                failed_pages=failed_pages,
            )

        return JmPlainDownload(
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


async def download_book(
    book_id: str,
    *,
    config: Any,
    password: str | None = None,
) -> tuple[JmDownload, Path]:
    """下载整本，返回 ``(结果, 任务目录)``。

    ``password`` 给出时每章各出一份 AES-256 加密 PDF，并打包成**无密码** zip
    （自动提取用）；``None`` 时所有章节合成一份**未加密** PDF（``uid`` 模式用，
    便于 PDF 解析）。调用方负责在发送或登记完成后清理任务目录
    （``cleanup_download_path``）；本函数抛异常或被取消时自己清理，不留残留目录。
    """
    task_dir = ensure_dir(_JM_DOWNLOAD_DIR / uuid.uuid4().hex)
    loop = asyncio.get_running_loop()
    options: dict[str, Any] = {
        "settings": build_settings(config),
        "max_chapters": int(getattr(config, "jm_max_chapters", 0)),
        "chapter_max_file_size_mb": int(
            getattr(config, "jm_chapter_max_file_size", 100)
        ),
        "pdf_dpi": float(getattr(config, "jm_pdf_dpi", 150.0)),
        "image_quality": int(getattr(config, "jm_image_quality", 95)),
    }
    download: Callable[[], JmDownload]
    if password is None:
        download = functools.partial(_download_plain_sync, book_id, task_dir, **options)
    else:
        download = functools.partial(
            _download_archive_sync, book_id, task_dir, password=password, **options
        )
    future: asyncio.Future[JmDownload] = loop.run_in_executor(_DOWNLOAD_POOL, download)
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
