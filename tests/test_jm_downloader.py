from __future__ import annotations

from collections.abc import Sequence
import re
from types import SimpleNamespace
from typing import Any, Literal, TypeAlias
import zipfile
from pathlib import Path

import asyncio

import fitz
import pytest
from jmcpy.imaging import block_count, descramble
from jmcpy import Book
from jmcpy.models import Picture
from PIL import Image

import Undefined.jm.client as jm_client
import Undefined.jm.downloader as jm_downloader
from Undefined.jm.downloader import (
    JmChapterArchive,
    JmDownload,
    JmPlainDownload,
    download_book,
)

#: ``(章节号, 章节序号[, 章节标题])``，测试里用来描述一个本子的章节表
ChapterSpec: TypeAlias = tuple[int, int] | tuple[int, int, str]

#: 章节文件名里的三位序号（``JM<车号> <序号>[ <标题>].pdf``；整本 PDF 名没有序号）
_CHAPTER_INDEX_RE = re.compile(r"^JM\d{6,} (\d{3})(?: |\.)")


class _FakeChapter:
    def __init__(self, chapter_id: int, pages: int, *, title: str = "") -> None:
        self.chapter_id = chapter_id
        self.title = title
        self.pictures = tuple(f"{index:05d}.webp" for index in range(1, pages + 1))

    def __len__(self) -> int:
        return len(self.pictures)


class _FakeArtifact:
    def __init__(self, path: Path, size: int, picture: Any) -> None:
        self.path = path
        self.size = size
        self.picture = picture


class _FakeDownloadResult:
    def __init__(self, paths: list[Path], page_size: int, failures: int = 0) -> None:
        self.paths = tuple(paths)
        self.failures = tuple(object() for _ in range(failures))
        self._page_size = page_size
        self._artifacts = [
            _FakeArtifact(path, page_size, _fake_picture(path)) for path in paths
        ]

    def __iter__(self) -> Any:
        return iter(self._artifacts)


def _fake_picture(path: Path) -> Any:
    return SimpleNamespace(
        filename=path.name,
        chapter_id=111,
        scramble_id=0,
        suffix=path.suffix,
    )


def _fake_book(
    chapters: Sequence[ChapterSpec],
    *,
    title: str = "测试 本子/标题",
    duplicate_orders: bool = False,
) -> Any:
    entries = []
    for item in chapters:
        chapter_id, order = item[0], item[1]
        chapter_title = item[2] if len(item) > 2 else ""
        if duplicate_orders:
            # 服务端异常数据：两条章节都报同一个序号
            order = 1
        entries.append(
            SimpleNamespace(chapter_id=chapter_id, order=order, title=chapter_title)
        )
    return SimpleNamespace(
        book_id=1114751,
        title=title,
        chapters=tuple(entries),
    )


class _FakeClient:
    """记录调用参数的 jmcpy Client 替身。"""

    instances: list["_FakeClient"] = []

    def __init__(
        self,
        settings: Any,
        *,
        chapters: Sequence[ChapterSpec],
        page_size: int,
        book_title: str,
        duplicate_orders: bool = False,
    ) -> None:
        self.settings = settings
        self.chapters = chapters
        self.page_size = page_size
        self.book_title = book_title
        self.duplicate_orders = duplicate_orders
        self.downloads: list[dict[str, Any]] = []
        _FakeClient.instances.append(self)

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info: object) -> Literal[False]:
        return False

    def get_book(self, book_id: str) -> Any:
        self.book_id = book_id
        return _fake_book(
            self.chapters,
            title=self.book_title,
            duplicate_orders=self.duplicate_orders,
        )

    def get_chapter(self, chapter_id: int) -> _FakeChapter:
        self.chapter_id = chapter_id
        # 第一章没有图片，用于验证空章节被跳过
        return _FakeChapter(chapter_id, 0 if chapter_id == 999 else 2)

    def download(
        self,
        chapter: _FakeChapter,
        *,
        output: Any,
        dest: Path,
        decode: bool,
        concurrency: int,
    ) -> _FakeDownloadResult:
        dest.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for name in chapter.pictures:
            path = dest / name
            path.write_bytes(b"page")
            paths.append(path)
        self.downloads.append(
            {
                "chapter_id": chapter.chapter_id,
                "output": output,
                "dest": dest,
                "concurrency": concurrency,
                "decode": decode,
            }
        )
        return _FakeDownloadResult(paths, page_size=self.page_size)


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _FakeClient.instances.clear()
    monkeypatch.setattr(jm_downloader, "_JM_DOWNLOAD_DIR", tmp_path / "jm")


def _install_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    chapters: Sequence[ChapterSpec],
    page_size: int = 10,
    book_title: str = "测试 本子/标题",
    duplicate_orders: bool = False,
) -> None:
    def _factory(settings: Any) -> _FakeClient:
        return _FakeClient(
            settings,
            chapters=chapters,
            page_size=page_size,
            book_title=book_title,
            duplicate_orders=duplicate_orders,
        )

    monkeypatch.setattr(jm_downloader, "Client", _factory)


def _write_stub_pdf(output: Path, pages: list[tuple[Path, Picture]]) -> None:
    """替身 PDF：页数与传入页面一致，内容留空（只为验证结构，不解码图片）。"""
    document = fitz.open()
    for _ in pages:
        document.new_page(width=100, height=150)
    document.save(str(output), garbage=3, deflate=True)
    document.close()


def _capture_write_pdf(
    monkeypatch: pytest.MonkeyPatch,
    *,
    oversize_orders: set[int] | None = None,
    empty_orders: set[int] | None = None,
) -> dict[str, Any]:
    """替换 ``_write_pdf``：按输出名记录每章参数，可指定某些章节超限/无页。

    ``oversize_orders`` / ``empty_orders`` 按**章节序号**（文件名里的三位数）生效，
    与真实实现一致：超限不落盘并返回 oversize。
    """
    captured: dict[str, Any] = {"calls": []}
    oversize = oversize_orders or set()
    empty = empty_orders or set()

    def _write_pdf(
        pages: Any,
        output: Path,
        *,
        dpi: float,
        quality: int,
        password: str | None,
        limit_bytes: int | None,
    ) -> Any:
        page_list = list(pages)
        output.parent.mkdir(parents=True, exist_ok=True)
        # 章节序号写在文件名里；整本 PDF（uid 路径）没有序号，超限判定按 1 处理
        match = _CHAPTER_INDEX_RE.search(output.name)
        index = int(match.group(1)) if match else 1
        captured["calls"].append(
            {
                "output": output,
                "pages": page_list,
                "sources": [path for path, _picture in page_list],
                "dpi": dpi,
                "quality": quality,
                "password": password,
                "limit_bytes": limit_bytes,
            }
        )
        if index in oversize:
            return jm_downloader._PdfBuild("oversize", None, len(page_list), 1234, 0)
        if index in empty:
            return jm_downloader._PdfBuild("empty", None, 0, 0, len(page_list))
        _write_stub_pdf(output, page_list)
        return jm_downloader._PdfBuild(
            "ok", output, len(page_list), output.stat().st_size, 0
        )

    monkeypatch.setattr(jm_downloader, "_write_pdf", _write_pdf)
    return captured


def _config(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "jm_session_dir": "",
        "jm_request_timeout": 20.0,
        "jm_image_timeout": 60.0,
        "jm_download_concurrency": 4,
        "jm_max_chapters": 0,
        "jm_chapter_max_file_size": 100,
        "jm_pdf_dpi": 150.0,
        "jm_image_quality": 95,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _archive(result: JmDownload) -> JmChapterArchive:
    assert isinstance(result, JmChapterArchive), result
    return result


def _plain(result: JmDownload) -> JmPlainDownload:
    assert isinstance(result, JmPlainDownload), result
    return result


def _zip_entries(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as archive:
        return archive.namelist()


@pytest.mark.asyncio
async def test_download_book_writes_one_pdf_per_chapter_into_zip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(
        monkeypatch,
        chapters=[(111, 1, "序章"), (222, 2)],
    )
    captured = _capture_write_pdf(monkeypatch)

    result, task_dir = await download_book(
        "1114751", config=_config(), password="Ab3xK9Qm"
    )
    archive = _archive(result)

    assert archive.status == "ok"
    assert archive.chapter_count == 2
    assert archive.downloaded_chapters == 2
    assert archive.skipped_chapters == 0
    assert archive.page_count == 4
    assert archive.zip_path is not None
    assert archive.zip_path.name == "JM1114751 测试 本子_标题.zip"
    assert archive.zip_path.parent == task_dir
    assert archive.size_bytes == archive.zip_path.stat().st_size
    # 每章一份 PDF：序号补零，有标题的带标题；空标题只留序号
    assert _zip_entries(archive.zip_path) == [
        "JM1114751 001 序章.pdf",
        "JM1114751 002.pdf",
    ]
    assert [(pdf.order, pdf.title, pdf.page_count) for pdf in archive.pdfs] == [
        (1, "序章", 2),
        (2, "", 2),
    ]
    # 每个章节 PDF 单独写盘，页序 = 章节顺序 × 章节内页序
    assert [call["output"].name for call in captured["calls"]] == [
        "JM1114751 001 序章.pdf",
        "JM1114751 002.pdf",
    ]
    assert [path.name for path in captured["calls"][0]["sources"]] == [
        "00001.webp",
        "00002.webp",
    ]
    assert all(call["password"] == "Ab3xK9Qm" for call in captured["calls"])
    assert all(call["dpi"] == 150.0 for call in captured["calls"])
    assert all(call["limit_bytes"] == 100 * 1024 * 1024 for call in captured["calls"])
    # 章节 PDF 已进 zip，任务目录里只留最终交付物
    assert sorted(path.name for path in task_dir.glob("*") if path.is_file()) == [
        "JM1114751 测试 本子_标题.zip"
    ]
    client = _FakeClient.instances[0]
    assert [item["chapter_id"] for item in client.downloads] == [111, 222]
    assert client.downloads[0]["dest"] != client.downloads[1]["dest"]
    assert client.downloads[0]["concurrency"] == 4
    # 取服务端原始字节：解扰与编码交给写 PDF 那一步，避免多一代有损压缩
    assert client.downloads[0]["decode"] is False


@pytest.mark.asyncio
async def test_download_book_sorts_chapters_by_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 服务端返回顺序不可信：按 order 排序后 zip 条目才是阅读顺序
    _install_client(monkeypatch, chapters=[(111, 2), (222, 1)])
    captured = _capture_write_pdf(monkeypatch)

    result, _ = await download_book("1114751", config=_config(), password="Ab3xK9Qm")
    archive = _archive(result)

    assert archive.status == "ok"
    assert [item["chapter_id"] for item in _FakeClient.instances[0].downloads] == [
        222,
        111,
    ]
    # 章节序号跟着阅读顺序走，与章节号无关
    assert [call["output"].name for call in captured["calls"]] == [
        "JM1114751 001.pdf",
        "JM1114751 002.pdf",
    ]
    assert [pdf.chapter_id for pdf in archive.pdfs] == [222, 111]
    assert [path.parent.name for path in captured["calls"][0]["sources"]] == [
        "c001",
        "c001",
    ]
    assert [path.parent.name for path in captured["calls"][1]["sources"]] == [
        "c002",
        "c002",
    ]


@pytest.mark.asyncio
async def test_download_book_falls_back_to_book_id_for_single_chapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(monkeypatch, chapters=[])
    captured = _capture_write_pdf(monkeypatch)

    result, _ = await download_book("1114751", config=_config(), password="Ab3xK9Qm")
    archive = _archive(result)

    assert archive.status == "ok"
    assert archive.chapter_count == 1
    assert _FakeClient.instances[0].downloads[0]["chapter_id"] == 1114751
    assert _zip_entries(archive.zip_path) == ["JM1114751 001.pdf"]  # type: ignore[arg-type]
    assert len(captured["calls"]) == 1


@pytest.mark.asyncio
async def test_download_book_skips_empty_chapters_and_honours_max_chapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(monkeypatch, chapters=[(999, 1), (111, 2), (222, 3)])
    _capture_write_pdf(monkeypatch)

    result, _ = await download_book(
        "1114751", config=_config(jm_max_chapters=2), password="Ab3xK9Qm"
    )
    archive = _archive(result)

    # 只取前两章，其中一章没有图片
    assert archive.chapter_count == 3
    assert archive.downloaded_chapters == 1
    assert archive.skipped_chapters == 0, "服务端没给图的章节不算「被跳过」"
    assert archive.page_count == 2
    assert [item["chapter_id"] for item in _FakeClient.instances[0].downloads] == [111]
    # 序号取自服务端章节序号：被跳过的第 1 章仍占号，所以留下的是 002
    assert _zip_entries(archive.zip_path) == ["JM1114751 002.pdf"]  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_download_book_skips_oversized_chapter_and_keeps_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单章超限只丢那一章：其余章节照常打包，状态是 partial。"""
    _install_client(monkeypatch, chapters=[(111, 1), (222, 2), (333, 3)])
    captured = _capture_write_pdf(monkeypatch, oversize_orders={2})

    result, _ = await download_book(
        "1114751", config=_config(jm_chapter_max_file_size=1), password="Ab3xK9Qm"
    )
    archive = _archive(result)

    assert archive.status == "partial"
    assert archive.ok
    assert archive.skipped_chapters == 1
    assert archive.downloaded_chapters == 3
    assert archive.page_count == 4
    assert len(captured["calls"]) == 3
    assert _zip_entries(archive.zip_path) == [  # type: ignore[arg-type]
        "JM1114751 001.pdf",
        "JM1114751 003.pdf",
    ]
    assert [pdf.order for pdf in archive.pdfs] == [1, 3]


@pytest.mark.asyncio
async def test_download_book_keeps_every_chapter_when_orders_collide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """服务端返回重复章节序号时不能互相覆盖：目录名与 zip 条目名都必须唯一。"""
    _install_client(
        monkeypatch,
        chapters=[(111, 1, "序章"), (222, 2, "序章"), (333, 3)],
        duplicate_orders=True,
    )
    _capture_write_pdf(monkeypatch)

    result, task_dir = await download_book(
        "1114751", config=_config(), password="Ab3xK9Qm"
    )
    archive = _archive(result)

    # 三章都出 PDF，没有一份被同名覆盖掉
    assert archive.status == "ok"
    assert archive.page_count == 6
    assert len(archive.pdfs) == 3
    assert [item["dest"].name for item in _FakeClient.instances[0].downloads] == [
        "c001",
        "c002",
        "c003",
    ]
    zip_path = archive.zip_path
    assert zip_path is not None
    assert sorted(_zip_entries(zip_path)) == [
        "JM1114751 001 序章.pdf",
        "JM1114751 002 序章.pdf",
        "JM1114751 003.pdf",
    ]
    # zip 条目确实有三份不同的 PDF 内容，各自页数正确
    with zipfile.ZipFile(zip_path) as archive_file:
        assert sorted(
            fitz.open(stream=archive_file.read(name), filetype="pdf").page_count
            for name in archive_file.namelist()
        ) == [2, 2, 2]
    # 报告里保留服务端原始序号（重复），只有产物名做了去重
    assert [pdf.order for pdf in archive.pdfs] == [1, 1, 1]
    assert [pdf.chapter_id for pdf in archive.pdfs] == [111, 222, 333]
    assert sorted(path.name for path in task_dir.glob("*.pdf")) == []


@pytest.mark.asyncio
async def test_download_book_skips_chapter_whose_pages_all_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(monkeypatch, chapters=[(111, 1), (222, 2)])
    _capture_write_pdf(monkeypatch, empty_orders={2})

    result, _ = await download_book("1114751", config=_config(), password="Ab3xK9Qm")
    archive = _archive(result)

    assert archive.status == "partial"
    assert archive.skipped_chapters == 1
    assert _zip_entries(archive.zip_path) == ["JM1114751 001.pdf"]  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_download_book_reports_empty_when_no_chapter_makes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """所有章节都超限时不出 zip：交给上层只发信息节点。"""
    _install_client(monkeypatch, chapters=[(111, 1), (222, 2)])
    _capture_write_pdf(monkeypatch, oversize_orders={1, 2})

    result, task_dir = await download_book(
        "1114751", config=_config(jm_chapter_max_file_size=1), password="Ab3xK9Qm"
    )
    archive = _archive(result)

    assert archive.status == "empty"
    assert not archive.ok
    assert archive.zip_path is None
    assert archive.size_bytes is None
    assert archive.page_count == 0
    assert archive.skipped_chapters == 2
    assert list(task_dir.glob("*.zip")) == []


@pytest.mark.asyncio
async def test_download_book_reports_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(monkeypatch, chapters=[(999, 1)])
    captured = _capture_write_pdf(monkeypatch)

    result, task_dir = await download_book(
        "1114751", config=_config(), password="Ab3xK9Qm"
    )
    archive = _archive(result)

    assert archive.status == "empty"
    assert archive.zip_path is None
    assert captured["calls"] == []
    assert list(task_dir.glob("*")) == []


def test_chapter_limit_bytes_follows_config() -> None:
    assert jm_downloader._chapter_limit_bytes(0) is None
    assert jm_downloader._chapter_limit_bytes(2) == 2 * 1024 * 1024


@pytest.mark.asyncio
async def test_download_book_merges_into_plain_pdf_without_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """uid 路径维持现状：所有章节合成一份未加密 PDF，不产生 zip。"""
    _install_client(monkeypatch, chapters=[(111, 1), (222, 2)])
    captured = _capture_write_pdf(monkeypatch)

    result, task_dir = await download_book("1114751", config=_config(), password=None)
    plain = _plain(result)

    assert plain.status == "ok"
    assert plain.ok
    assert plain.chapter_count == 2
    assert plain.downloaded_chapters == 2
    assert plain.page_count == 4
    assert plain.pdf_path is not None
    assert plain.pdf_path.name == "JM1114751 测试 本子_标题.pdf"
    assert len(captured["calls"]) == 1
    assert captured["calls"][0]["password"] is None
    assert [path.name for path in captured["calls"][0]["sources"]] == [
        "00001.webp",
        "00002.webp",
        "00001.webp",
        "00002.webp",
    ]
    assert list(task_dir.glob("*.zip")) == []


@pytest.mark.asyncio
async def test_download_book_plain_reports_oversize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(monkeypatch, chapters=[(111, 1), (222, 2)])
    _capture_write_pdf(monkeypatch, oversize_orders={1})

    result, _ = await download_book(
        "1114751", config=_config(jm_chapter_max_file_size=1), password=None
    )
    plain = _plain(result)

    assert plain.status == "oversize"
    assert plain.pdf_path is None
    assert not plain.ok


def test_build_settings_maps_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        jm_client,
        "get_request_proxy",
        lambda *_args, **_kwargs: "http://127.0.0.1:7890",
    )

    settings = jm_client.build_settings(
        _config(
            jm_use_proxy=True,
            jm_session_dir="/tmp/jmcpy-home",
            jm_request_timeout=45.0,
            jm_image_timeout=120.0,
            jm_download_concurrency=16,
        )
    )

    assert settings.proxy == "http://127.0.0.1:7890"
    assert settings.timeout == 45.0
    assert settings.image_timeout == 120.0
    assert settings.concurrency == 16
    assert settings.home == Path("/tmp/jmcpy-home")


def test_build_settings_leaves_home_unset_when_session_dir_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jm_client, "get_request_proxy", lambda *_args, **_kwargs: None)

    settings = jm_client.build_settings(_config(jm_session_dir="  "))

    assert settings.home is None
    assert settings.proxy is None


def _page_png(path: Path, size: tuple[int, int], *, band: int = 0) -> Path:
    image = Image.new("RGB", size, (255, 255, 255))
    for index in range(0, size[1], 7):
        colour = (band, index % 256, 0)
        image.paste(colour, (0, index, size[0], min(index + 3, size[1])))
    image.save(path, format="PNG")
    return path


def test_write_pdf_keeps_one_page_scale_for_every_page(tmp_path: Path) -> None:
    pages = [
        (_page_png(tmp_path / "a.png", (600, 900)), _fake_picture(Path("00001.webp"))),
        (
            _page_png(tmp_path / "b.png", (900, 600), band=10),
            _fake_picture(Path("00002.webp")),
        ),
        (
            _page_png(tmp_path / "c.png", (600, 900), band=20),
            _fake_picture(Path("00003.webp")),
        ),
    ]

    build = jm_downloader._write_pdf(
        pages,
        tmp_path / "out.pdf",
        dpi=150.0,
        quality=95,
        password="Ab3xK9Qm",
        limit_bytes=None,
    )

    assert build.status == "ok"
    assert build.path is not None
    assert build.page_count == 3
    assert build.failed_pages == 0
    doc = fitz.open(build.path)
    assert doc.needs_pass
    assert doc.authenticate("Ab3xK9Qm") > 0
    assert doc.page_count == 3
    # 每页都按同一个 DPI 换算物理尺寸，不再出现第一页 150 DPI、其余 72 DPI 的错位
    expected = [(288, 432), (432, 288), (288, 432)]
    for page, (width, height) in zip(doc, expected):
        assert (round(page.rect.width), round(page.rect.height)) == (width, height)
        info = doc.extract_image(page.get_images(full=True)[0][0])
        assert info["ext"] == "jpeg"
        assert (info["width"], info["height"]) == (
            width * 150 // 72,
            height * 150 // 72,
        )


def test_load_page_descrambles_server_blocks(tmp_path: Path) -> None:
    original = Image.new("RGB", (30, 100))
    for index in range(10):
        original.paste(
            (index * 25 % 256, index * 17 % 256, index * 9 % 256),
            (0, index * 10, 30, index * 10 + 10),
        )
    # 服务端把竖直分块打乱；10 块时是整块反转，反转两次即还原
    scrambled = descramble(original, 10)
    path = tmp_path / "00001.webp"
    scrambled.save(path, format="PNG")
    picture = Picture(
        chapter_id=42, index=1, filename="00001.webp", url="", scramble_id=42
    )

    restored = jm_downloader._load_page(path, picture)

    assert block_count(42, 42, "00001.webp") == 10
    assert restored.tobytes() == original.tobytes()


def test_write_pdf_can_skip_encryption(tmp_path: Path) -> None:
    pages = [
        (_page_png(tmp_path / "a.png", (300, 400)), _fake_picture(Path("00001.webp")))
    ]

    build = jm_downloader._write_pdf(
        pages,
        tmp_path / "plain.pdf",
        dpi=150.0,
        quality=95,
        password=None,
        limit_bytes=None,
    )

    assert build.status == "ok" and build.path is not None
    doc = fitz.open(build.path)
    assert not doc.needs_pass, "uid 模式必须输出未加密 PDF，否则 PDF 解析工具打不开"


def test_write_pdf_stops_when_encoded_size_exceeds_limit(tmp_path: Path) -> None:
    pages = [
        (_page_png(tmp_path / "a.png", (600, 900)), _fake_picture(Path("00001.webp")))
    ]

    build = jm_downloader._write_pdf(
        pages,
        tmp_path / "big.pdf",
        dpi=150.0,
        quality=95,
        password=None,
        limit_bytes=1,
    )

    assert build.status == "oversize"
    assert build.path is None
    assert not (tmp_path / "big.pdf").exists(), "提前中止时不应留下半成品 PDF"


def test_write_pdf_skips_undecodable_page(tmp_path: Path) -> None:
    good = _page_png(tmp_path / "good.png", (300, 400))
    broken = tmp_path / "broken.webp"
    broken.write_bytes(b"not an image")
    pages = [
        (good, _fake_picture(Path("00001.webp"))),
        (broken, _fake_picture(Path("00002.webp"))),
        (good, _fake_picture(Path("00003.webp"))),
    ]

    build = jm_downloader._write_pdf(
        pages,
        tmp_path / "partial.pdf",
        dpi=150.0,
        quality=95,
        password=None,
        limit_bytes=None,
    )

    assert build.status == "ok"
    assert build.page_count == 2, "坏页被跳过，其余页照常出 PDF"
    assert build.failed_pages == 1


def test_write_pdf_reports_empty_when_every_page_fails(tmp_path: Path) -> None:
    broken = tmp_path / "broken.webp"
    broken.write_bytes(b"not an image")

    build = jm_downloader._write_pdf(
        [(broken, _fake_picture(Path("00001.webp")))],
        tmp_path / "empty.pdf",
        dpi=150.0,
        quality=95,
        password=None,
        limit_bytes=None,
    )

    assert build.status == "empty"
    assert build.path is None
    assert build.failed_pages == 1


def test_write_zip_has_no_password_and_keeps_entry_order(tmp_path: Path) -> None:
    zip_path = tmp_path / "book.zip"

    size = jm_downloader._write_zip(
        [("JM1 001.pdf", b"%PDF-1.4 first"), ("JM1 002 a.pdf", b"%PDF-1.4 second")],
        zip_path,
    )

    assert size == zip_path.stat().st_size
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.namelist() == ["JM1 001.pdf", "JM1 002 a.pdf"]
        # zip 不加密：没有密码位，条目可以直接读
        assert all(not info.flag_bits & 0x1 for info in archive.infolist())
        assert archive.read("JM1 001.pdf") == b"%PDF-1.4 first"


@pytest.mark.asyncio
async def test_download_book_cleans_up_when_download_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(jm_downloader, "_download_archive_sync", _boom)

    with pytest.raises(RuntimeError, match="boom"):
        await download_book("1114751", config=_config(), password="Ab3xK9Qm")

    leftovers = list((tmp_path / "jm").glob("*"))
    assert leftovers == [], f"异常路径不得留下任务目录: {leftovers}"


@pytest.mark.asyncio
async def test_download_book_counts_failed_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 每章 2 页，其中 1 页下载失败：失败数应汇总到 failed_pages
    _install_client(monkeypatch, chapters=[(111, 1)])
    _capture_write_pdf(monkeypatch)

    original_download = _FakeClient.download

    def _download_with_failure(self: Any, chapter: Any, **kwargs: Any) -> Any:
        result = original_download(self, chapter, **kwargs)
        result.failures = (object(),)
        return result

    monkeypatch.setattr(_FakeClient, "download", _download_with_failure)

    result, _ = await download_book("1114751", config=_config(), password="Ab3xK9Qm")
    archive = _archive(result)

    assert archive.status == "ok"
    assert archive.failed_pages == 1


@pytest.mark.asyncio
async def test_download_book_cleans_up_after_cancellation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """取消后线程仍在写盘：必须等它结束再清理，不留残留原图/未加密 PDF。"""
    import threading

    started = threading.Event()
    release = threading.Event()

    def _slow(*_args: Any, **_kwargs: Any) -> Any:
        started.set()
        release.wait(10)
        return JmChapterArchive(
            status="empty",
            book=Book(book_id=1114751, title="测试本子"),
            zip_path=None,
            size_bytes=None,
            page_count=0,
            chapter_count=1,
            downloaded_chapters=0,
            failed_pages=0,
            skipped_chapters=0,
        )

    monkeypatch.setattr(jm_downloader, "_download_archive_sync", _slow)

    task = asyncio.create_task(
        download_book("1114751", config=_config(), password="Ab3xK9Qm")
    )
    assert await asyncio.to_thread(started.wait, 10), "下载线程没能启动"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # 取消时目录还在（线程仍在写），放行线程后由回调清理
    assert list((tmp_path / "jm").glob("*")), "取消瞬间不应删除仍在写入的目录"
    release.set()

    for _ in range(100):
        if not list((tmp_path / "jm").glob("*")):
            break
        await asyncio.sleep(0.05)
    assert list((tmp_path / "jm").glob("*")) == [], "取消后必须清掉任务目录"
