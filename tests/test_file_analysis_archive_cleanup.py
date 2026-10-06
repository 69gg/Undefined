from __future__ import annotations

import io
from pathlib import Path
import tarfile
from typing import Any
from unittest.mock import Mock

import pytest

from Undefined.skills.agents.file_analysis_agent.tools.cleanup_temp import (
    handler as cleanup_handler,
)
from Undefined.skills.agents.file_analysis_agent.tools.extract_archive import (
    handler as archive_handler,
)


def _archive_context(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    root = tmp_path / "downloads"
    task_dir = root / "task"
    task_dir.mkdir(parents=True)
    return {"download_cache_dir": root}, task_dir / "input.tar"


def _write_tar(path: Path, member: tarfile.TarInfo, content: bytes = b"") -> None:
    with tarfile.open(path, "w") as archive:
        if member.isfile():
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        else:
            archive.addfile(member)


@pytest.mark.asyncio
async def test_archive_extracts_regular_tar_inside_task_directory(
    tmp_path: Path,
) -> None:
    context, path = _archive_context(tmp_path)
    _write_tar(path, tarfile.TarInfo("nested/readme.txt"), b"safe contents")

    result = await archive_handler.execute(
        {"file_path": str(path), "action": "extract"}, context
    )

    assert "已解压到" in result
    assert (path.parent / "extracted_input/nested/readme.txt").read_bytes() == (
        b"safe contents"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("member_kind", ["traversal", "symlink", "hardlink", "device"])
async def test_tar_rejects_unsafe_members(
    tmp_path: Path,
    member_kind: str,
) -> None:
    context, path = _archive_context(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"keep")
    if member_kind == "traversal":
        member = tarfile.TarInfo("../../../victim.txt")
    else:
        member = tarfile.TarInfo("unsafe")
        member.type = {
            "symlink": tarfile.SYMTYPE,
            "hardlink": tarfile.LNKTYPE,
            "device": tarfile.CHRTYPE,
        }[member_kind]
        member.linkname = "../../../victim.txt"
    _write_tar(path, member, b"overwritten")

    result = await archive_handler.execute(
        {"file_path": str(path), "action": "extract"}, context
    )

    assert "解析压缩包失败" in result
    assert victim.read_bytes() == b"keep"


@pytest.mark.asyncio
@pytest.mark.parametrize("target_kind", ["outside", "symlink", "other_task", "parent"])
async def test_archive_rejects_extract_target_outside_current_task(
    tmp_path: Path,
    target_kind: str,
) -> None:
    context, path = _archive_context(tmp_path)
    _write_tar(path, tarfile.TarInfo("readme.txt"), b"data")
    outside = tmp_path / "outside"
    outside.mkdir()
    if target_kind == "outside":
        target = outside
    elif target_kind == "symlink":
        target = path.parent / "alias"
        target.symlink_to(outside, target_is_directory=True)
    elif target_kind == "other_task":
        target = path.parent.parent / "other_task"
    else:
        target = path.parent

    result = await archive_handler.execute(
        {"file_path": str(path), "action": "extract", "extract_path": str(target)},
        context,
    )

    assert result.startswith("错误：")
    assert not (target / "readme.txt").exists()
    assert not (outside / "readme.txt").exists()


@pytest.mark.asyncio
async def test_archive_rejects_source_outside_download_cache(tmp_path: Path) -> None:
    context, _ = _archive_context(tmp_path)
    source = tmp_path / "outside.tar"
    _write_tar(source, tarfile.TarInfo("readme.txt"), b"data")

    result = await archive_handler.execute(
        {"file_path": str(source), "action": "extract"}, context
    )

    assert "下载缓存目录内" in result


@pytest.mark.asyncio
async def test_archive_can_list_source_outside_download_cache(tmp_path: Path) -> None:
    context, _ = _archive_context(tmp_path)
    source = tmp_path / "outside.tar"
    _write_tar(source, tarfile.TarInfo("readme.txt"), b"data")

    result = await archive_handler.execute({"file_path": str(source)}, context)

    assert "readme.txt" in result
    assert not (tmp_path / "extracted_outside").exists()


@pytest.mark.asyncio
async def test_tar_without_safe_filter_refuses_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, path = _archive_context(tmp_path)
    _write_tar(path, tarfile.TarInfo("readme.txt"), b"data")
    monkeypatch.delattr(tarfile, "data_filter")
    extract_mock = Mock()
    monkeypatch.setattr(tarfile.TarFile, "extractall", extract_mock)

    result = await archive_handler.execute(
        {"file_path": str(path), "action": "extract"}, context
    )
    listed = await archive_handler.execute({"file_path": str(path)}, context)

    assert "缺少安全 TAR 解压能力" in result
    assert "readme.txt" in listed
    extract_mock.assert_not_called()
    assert not (path.parent / "extracted_input").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("task_uuid", ["../outside", "..", ".", "nested/task", "a\\b"])
async def test_cleanup_rejects_path_arguments(
    tmp_path: Path,
    task_uuid: str,
) -> None:
    context, _ = _archive_context(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep")

    result = await cleanup_handler.execute({"task_uuid": task_uuid}, context)

    assert "错误：" in result
    assert marker.read_text() == "keep"
    assert Path(context["download_cache_dir"]).is_dir()


@pytest.mark.asyncio
async def test_cleanup_rejects_absolute_path_and_symbolic_link(tmp_path: Path) -> None:
    context, _ = _archive_context(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep")
    alias = Path(context["download_cache_dir"]) / "alias"
    alias.symlink_to(outside, target_is_directory=True)

    for task_uuid in (str(outside), "alias"):
        result = await cleanup_handler.execute({"task_uuid": task_uuid}, context)
        assert "错误：" in result
    assert marker.read_text() == "keep"
    assert alias.is_symlink()


@pytest.mark.asyncio
@pytest.mark.parametrize("clear_all", [True, False])
async def test_cleanup_removes_only_cache_directories(
    tmp_path: Path,
    clear_all: bool,
) -> None:
    context, path = _archive_context(tmp_path)
    path.write_bytes(b"data")
    root = Path(context["download_cache_dir"])
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep")
    alias = root / "alias"
    alias.symlink_to(outside, target_is_directory=True)

    result = await cleanup_handler.execute(
        {} if clear_all else {"task_uuid": "task"}, context
    )

    assert "已清理" in result
    assert not path.parent.exists()
    assert root.is_dir()
    assert alias.is_symlink()
    assert marker.read_text() == "keep"
