from __future__ import annotations

from pathlib import Path

import pytest

from Undefined.webui.routes._runtime import _resolve_chat_image_path


def test_resolve_chat_image_path_accepts_cache_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    image = tmp_path / "data" / "cache" / "render" / "stats_table.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"fake-png")

    resolved = _resolve_chat_image_path(str(image))
    assert resolved == image.resolve()


def test_resolve_chat_image_path_rejects_outside_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"fake-png")

    assert _resolve_chat_image_path(str(outside)) is None


def test_resolve_chat_image_path_rejects_non_image_suffix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    file_path = tmp_path / "data" / "cache" / "render" / "note.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("hello", encoding="utf-8")

    assert _resolve_chat_image_path(str(file_path)) is None
