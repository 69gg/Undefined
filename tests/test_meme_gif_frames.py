from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

from Undefined.memes.service import (
    _compose_grid,
    _extract_gif_frames,
    _sample_frame_indices,
)


def _make_gif(path: Path, n_frames: int, size: tuple[int, int] = (4, 4)) -> None:
    """创建一个包含 *n_frames* 帧的 GIF 文件。"""
    frames = [
        Image.new("RGBA", size, (i * 30 % 256, i * 60 % 256, i * 90 % 256, 255))
        for i in range(n_frames)
    ]
    frames[0].save(
        path,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=100,
    )


# ── _sample_frame_indices ──


def test_sample_indices_basic() -> None:
    result = _sample_frame_indices(10, 4)
    assert result[0] == 0
    assert result[-1] == 9
    assert len(result) == 4


def test_sample_indices_more_than_total() -> None:
    result = _sample_frame_indices(3, 10)
    assert result == [0, 1, 2]


def test_sample_indices_two() -> None:
    result = _sample_frame_indices(20, 2)
    assert result == [0, 19]


def test_sample_indices_one() -> None:
    result = _sample_frame_indices(5, 1)
    assert result == [0]


def test_sample_indices_no_duplicates() -> None:
    result = _sample_frame_indices(3, 3)
    assert len(result) == len(set(result))


# ── _extract_gif_frames ──


def test_extract_frames_count(tmp_path: Path) -> None:
    gif_path = tmp_path / "test.gif"
    _make_gif(gif_path, 12)
    frames = _extract_gif_frames(gif_path, 6)
    assert len(frames) == 6
    for f in frames:
        assert f.mode == "RGBA"
        f.close()


def test_extract_frames_fewer_than_requested(tmp_path: Path) -> None:
    gif_path = tmp_path / "test.gif"
    _make_gif(gif_path, 3)
    frames = _extract_gif_frames(gif_path, 6)
    assert len(frames) == 3
    for f in frames:
        f.close()


def test_extract_frames_single_frame(tmp_path: Path) -> None:
    gif_path = tmp_path / "test.gif"
    _make_gif(gif_path, 1)
    frames = _extract_gif_frames(gif_path, 6)
    assert len(frames) == 1
    frames[0].close()


# ── _compose_grid ──


def test_compose_grid_output(tmp_path: Path) -> None:
    frames = [
        Image.new("RGBA", (10, 10), (255, 0, 0, 255)),
        Image.new("RGBA", (10, 10), (0, 255, 0, 255)),
        Image.new("RGBA", (10, 10), (0, 0, 255, 255)),
        Image.new("RGBA", (10, 10), (255, 255, 0, 255)),
    ]
    output = tmp_path / "grid.png"
    _compose_grid(frames, output)
    assert output.is_file()
    with Image.open(output) as grid:
        cols = math.ceil(math.sqrt(4))
        rows = math.ceil(4 / cols)
        assert grid.size == (cols * 10, rows * 10)
    for f in frames:
        f.close()


def test_compose_grid_single_frame(tmp_path: Path) -> None:
    frames = [Image.new("RGBA", (8, 8), (0, 0, 0, 255))]
    output = tmp_path / "grid_single.png"
    _compose_grid(frames, output)
    assert output.is_file()
    with Image.open(output) as grid:
        assert grid.size == (8, 8)
    frames[0].close()


def test_compose_grid_six_frames(tmp_path: Path) -> None:
    frames = [Image.new("RGBA", (10, 10), (i * 40, 0, 0, 255)) for i in range(6)]
    output = tmp_path / "grid6.png"
    _compose_grid(frames, output)
    assert output.is_file()
    with Image.open(output) as grid:
        cols = math.ceil(math.sqrt(6))
        rows = math.ceil(6 / cols)
        assert grid.size == (cols * 10, rows * 10)
    for f in frames:
        f.close()
