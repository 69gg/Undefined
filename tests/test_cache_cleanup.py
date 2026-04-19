"""Tests for Undefined.utils.cache.cleanup_cache_dir."""

from __future__ import annotations

import os
import time
from pathlib import Path

from Undefined.utils.cache import cleanup_cache_dir


class TestCleanupCacheDir:
    def test_empty_dir(self, tmp_path: Path) -> None:
        assert cleanup_cache_dir(tmp_path) == 0

    def test_old_files_removed(self, tmp_path: Path) -> None:
        old_file = tmp_path / "old.txt"
        old_file.write_text("data")
        # Set mtime to 30 days ago
        old_time = time.time() - 30 * 24 * 3600
        os.utime(old_file, (old_time, old_time))

        deleted = cleanup_cache_dir(tmp_path, max_age_seconds=7 * 24 * 3600)
        assert deleted == 1
        assert not old_file.exists()

    def test_new_files_kept(self, tmp_path: Path) -> None:
        new_file = tmp_path / "new.txt"
        new_file.write_text("data")
        # mtime = now (default), so it's fresh

        deleted = cleanup_cache_dir(tmp_path, max_age_seconds=7 * 24 * 3600)
        assert deleted == 0
        assert new_file.exists()

    def test_max_files_cap(self, tmp_path: Path) -> None:
        now = time.time()
        for i in range(5):
            f = tmp_path / f"file_{i}.txt"
            f.write_text("data")
            os.utime(f, (now - i, now - i))  # stagger mtime

        deleted = cleanup_cache_dir(tmp_path, max_age_seconds=0, max_files=3)
        assert deleted == 2
        remaining = list(tmp_path.iterdir())
        assert len(remaining) == 3

    def test_nonexistent_dir_created(self, tmp_path: Path) -> None:
        new_dir = tmp_path / "subdir" / "cache"
        assert not new_dir.exists()
        deleted = cleanup_cache_dir(new_dir)
        assert deleted == 0
        assert new_dir.is_dir()

    def test_mixed_ages(self, tmp_path: Path) -> None:
        now = time.time()
        # 1 old, 2 fresh
        old_f = tmp_path / "old.txt"
        old_f.write_text("old")
        os.utime(old_f, (now - 999999, now - 999999))

        for i in range(2):
            f = tmp_path / f"fresh_{i}.txt"
            f.write_text("fresh")

        deleted = cleanup_cache_dir(tmp_path, max_age_seconds=7 * 24 * 3600)
        assert deleted == 1
        assert not old_f.exists()

    def test_zero_max_age_skips_age_check(self, tmp_path: Path) -> None:
        old_file = tmp_path / "old.txt"
        old_file.write_text("data")
        old_time = time.time() - 999999
        os.utime(old_file, (old_time, old_time))

        deleted = cleanup_cache_dir(tmp_path, max_age_seconds=0, max_files=0)
        assert deleted == 0
        assert old_file.exists()

    def test_zero_max_files_skips_cap(self, tmp_path: Path) -> None:
        for i in range(10):
            (tmp_path / f"f{i}.txt").write_text("x")

        deleted = cleanup_cache_dir(tmp_path, max_age_seconds=0, max_files=0)
        assert deleted == 0
        assert len(list(tmp_path.iterdir())) == 10

    def test_both_age_and_cap(self, tmp_path: Path) -> None:
        now = time.time()
        # Create 5 files: 2 old (removed by age), 3 fresh
        for i in range(2):
            f = tmp_path / f"old_{i}.txt"
            f.write_text("old")
            os.utime(f, (now - 999999, now - 999999))
        for i in range(3):
            f = tmp_path / f"new_{i}.txt"
            f.write_text("new")
            os.utime(f, (now - i, now - i))

        deleted = cleanup_cache_dir(
            tmp_path, max_age_seconds=7 * 24 * 3600, max_files=2
        )
        # 2 removed by age + 1 removed by cap = 3
        assert deleted == 3
        assert len(list(tmp_path.iterdir())) == 2
