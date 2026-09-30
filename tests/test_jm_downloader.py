from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pytest

import Undefined.jm.client as jm_client
import Undefined.jm.downloader as jm_downloader
from Undefined.jm.downloader import download_book_pdf


class _FakeChapter:
    def __init__(self, chapter_id: int, pages: int) -> None:
        self.chapter_id = chapter_id
        self.pictures = tuple(f"{index:05d}.webp" for index in range(1, pages + 1))

    def __len__(self) -> int:
        return len(self.pictures)


class _FakeArtifact:
    def __init__(self, size: int) -> None:
        self.size = size


class _FakeDownloadResult:
    def __init__(self, paths: list[Path], page_size: int, failures: int = 0) -> None:
        self.paths = tuple(paths)
        self.failures = tuple(object() for _ in range(failures))
        self._page_size = page_size

    def __iter__(self) -> Any:
        for _ in self.paths:
            yield _FakeArtifact(self._page_size)


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
        concurrency: int,
        quality: int,
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
                "quality": quality,
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
        sources: Any, output: Path, *, dpi: float, quality: int, password: str | None
    ) -> Path:
        captured["sources"] = list(sources)
        captured["dpi"] = dpi
        captured["quality"] = quality
        captured["password"] = password
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"%PDF-1.4")
        return output

    monkeypatch.setattr(jm_downloader, "write_pdf", _write_pdf)
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
    assert client.downloads[0]["quality"] == 95


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
