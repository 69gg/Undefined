from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import asyncio

import fitz
import pytest
from jmcpy.imaging import block_count, descramble
from jmcpy import Book
from jmcpy.models import Picture
from PIL import Image

import Undefined.jm.client as jm_client
import Undefined.jm.downloader as jm_downloader
from Undefined.jm.downloader import JmDownload, download_book_pdf


class _FakeChapter:
    def __init__(self, chapter_id: int, pages: int) -> None:
        self.chapter_id = chapter_id
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


def _fake_book(chapter_ids: list[tuple[int, int]]) -> Any:
    return SimpleNamespace(
        book_id=1114751,
        title="测试 本子/标题",
        chapters=tuple(
            SimpleNamespace(chapter_id=chapter_id, order=order)
            for chapter_id, order in chapter_ids
        ),
    )


class _FakeClient:
    """记录调用参数的 jmcpy Client 替身。"""

    instances: list["_FakeClient"] = []

    def __init__(
        self, settings: Any, *, chapter_ids: list[tuple[int, int]], page_size: int
    ) -> None:
        self.settings = settings
        self.chapter_ids = chapter_ids
        self.page_size = page_size
        self.downloads: list[dict[str, Any]] = []
        _FakeClient.instances.append(self)

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info: object) -> Literal[False]:
        return False

    def get_book(self, book_id: str) -> Any:
        self.book_id = book_id
        return _fake_book(self.chapter_ids)

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
    chapter_ids: list[tuple[int, int]],
    page_size: int = 10,
) -> None:
    def _factory(settings: Any) -> _FakeClient:
        return _FakeClient(settings, chapter_ids=chapter_ids, page_size=page_size)

    monkeypatch.setattr(jm_downloader, "Client", _factory)


def _capture_write_pdf(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _write_pdf(
        pages: Any,
        output: Path,
        *,
        dpi: float,
        quality: int,
        password: str | None,
        limit_bytes: int | None,
    ) -> Any:
        captured["pages"] = list(pages)
        captured["sources"] = [path for path, _picture in pages]
        captured["dpi"] = dpi
        captured["quality"] = quality
        captured["password"] = password
        captured["limit_bytes"] = limit_bytes
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"%PDF-1.4")
        return jm_downloader._PdfBuild(
            "ok", output, len(captured["pages"]), output.stat().st_size, 0
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
        "jm_max_file_size": 100,
        "jm_pdf_dpi": 150.0,
        "jm_image_quality": 95,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_download_book_pdf_merges_all_chapters_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(monkeypatch, chapter_ids=[(111, 1), (222, 2)])
    captured = _capture_write_pdf(monkeypatch)

    result, task_dir = await download_book_pdf(
        "1114751", config=_config(), password="Ab3xK9Qm"
    )

    assert result.status == "ok"
    assert result.chapter_count == 2
    assert result.downloaded_chapters == 2
    assert result.page_count == 4
    assert result.pdf_path is not None
    assert result.pdf_path.name == "JM1114751 测试 本子_标题.pdf"
    assert result.pdf_path.parent == task_dir
    # 页序 = 章节顺序 × 章节内页序，且每章写入独立目录
    assert [path.name for path in captured["sources"]] == [
        "00001.webp",
        "00002.webp",
        "00001.webp",
        "00002.webp",
    ]
    assert captured["password"] == "Ab3xK9Qm"
    assert captured["dpi"] == 150.0
    client = _FakeClient.instances[0]
    assert [item["chapter_id"] for item in client.downloads] == [111, 222]
    assert client.downloads[0]["dest"] != client.downloads[1]["dest"]
    assert client.downloads[0]["concurrency"] == 4
    # 取服务端原始字节：解扰与编码交给写 PDF 那一步，避免多一代有损压缩
    assert client.downloads[0]["decode"] is False


@pytest.mark.asyncio
async def test_download_book_pdf_sorts_chapters_by_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 服务端返回顺序不可信：按 order 排序后合出的 PDF 才是阅读顺序
    _install_client(monkeypatch, chapter_ids=[(111, 2), (222, 1)])
    captured = _capture_write_pdf(monkeypatch)

    result, _ = await download_book_pdf(
        "1114751", config=_config(), password="Ab3xK9Qm"
    )

    assert result.status == "ok"
    assert [item["chapter_id"] for item in _FakeClient.instances[0].downloads] == [
        222,
        111,
    ]
    assert [path.parent.name for path in captured["sources"]] == [
        "c001",
        "c001",
        "c002",
        "c002",
    ]


@pytest.mark.asyncio
async def test_download_book_pdf_falls_back_to_book_id_for_single_chapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(monkeypatch, chapter_ids=[])
    _capture_write_pdf(monkeypatch)

    result, _ = await download_book_pdf(
        "1114751", config=_config(), password="Ab3xK9Qm"
    )

    assert result.status == "ok"
    assert result.chapter_count == 1
    assert _FakeClient.instances[0].downloads[0]["chapter_id"] == 1114751


@pytest.mark.asyncio
async def test_download_book_pdf_skips_empty_chapters_and_honours_max_chapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(monkeypatch, chapter_ids=[(999, 1), (111, 2), (222, 3)])
    _capture_write_pdf(monkeypatch)

    result, _ = await download_book_pdf(
        "1114751", config=_config(jm_max_chapters=2), password="Ab3xK9Qm"
    )

    # 只取前两章，其中一章没有图片
    assert result.chapter_count == 3
    assert result.downloaded_chapters == 1
    assert result.page_count == 2
    assert [item["chapter_id"] for item in _FakeClient.instances[0].downloads] == [111]


@pytest.mark.asyncio
async def test_download_book_pdf_stops_when_images_exceed_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(monkeypatch, chapter_ids=[(111, 1), (222, 2)], page_size=600_000)
    captured = _capture_write_pdf(monkeypatch)

    result, _ = await download_book_pdf(
        "1114751", config=_config(jm_max_file_size=1), password="Ab3xK9Qm"
    )

    assert result.status == "oversize"
    assert result.pdf_path is None
    assert captured == {}
    assert len(_FakeClient.instances[0].downloads) == 1


@pytest.mark.asyncio
async def test_download_book_pdf_reports_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(monkeypatch, chapter_ids=[(999, 1)])
    captured = _capture_write_pdf(monkeypatch)

    result, _ = await download_book_pdf(
        "1114751", config=_config(), password="Ab3xK9Qm"
    )

    assert result.status == "empty"
    assert result.pdf_path is None
    assert captured == {}


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


@pytest.mark.asyncio
async def test_download_book_pdf_cleans_up_when_download_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(jm_downloader, "_download_sync", _boom)

    with pytest.raises(RuntimeError, match="boom"):
        await download_book_pdf("1114751", config=_config(), password="Ab3xK9Qm")

    leftovers = list((tmp_path / "jm").glob("*"))
    assert leftovers == [], f"异常路径不得留下任务目录: {leftovers}"


@pytest.mark.asyncio
async def test_download_book_pdf_counts_failed_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 每章 2 页，其中 1 页下载失败：失败数应汇总到 JmDownload.failed_pages
    _install_client(monkeypatch, chapter_ids=[(111, 1)])
    _capture_write_pdf(monkeypatch)

    original_download = _FakeClient.download

    def _download_with_failure(self: Any, chapter: Any, **kwargs: Any) -> Any:
        result = original_download(self, chapter, **kwargs)
        result.failures = (object(),)
        return result

    monkeypatch.setattr(_FakeClient, "download", _download_with_failure)

    result, _ = await download_book_pdf(
        "1114751", config=_config(), password="Ab3xK9Qm"
    )

    assert result.status == "ok"
    assert result.failed_pages == 1


@pytest.mark.asyncio
async def test_download_book_pdf_cleans_up_after_cancellation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """取消后线程仍在写盘：必须等它结束再清理，不留残留原图/未加密 PDF。"""
    import threading

    started = threading.Event()
    release = threading.Event()

    def _slow(*_args: Any, **_kwargs: Any) -> Any:
        started.set()
        release.wait(10)
        return JmDownload(
            status="ok",
            book=Book(book_id=1114751, title="测试本子"),
            pdf_path=None,
            page_count=0,
            size_bytes=0,
            chapter_count=1,
            downloaded_chapters=0,
            failed_pages=0,
        )

    monkeypatch.setattr(jm_downloader, "_download_sync", _slow)

    task = asyncio.create_task(
        download_book_pdf("1114751", config=_config(), password=None)
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
