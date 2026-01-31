"""Cache helpers."""

from __future__ import annotations

import time
from pathlib import Path


def cleanup_cache_dir(
    path: Path,
    *,
    max_age_seconds: int = 7 * 24 * 60 * 60,
    max_files: int = 200,
) -> int:
    """Remove old files from a cache directory.

    Returns the number of files removed.
    """
    path.mkdir(parents=True, exist_ok=True)
    deleted = 0
    now = time.time()

    files = [item for item in path.iterdir() if item.is_file()]

    if max_age_seconds > 0:
        for item in files:
            try:
                age = now - item.stat().st_mtime
                if age > max_age_seconds:
                    item.unlink()
                    deleted += 1
            except OSError:
                continue

    if max_files > 0:
        files = [item for item in path.iterdir() if item.is_file()]
        if len(files) > max_files:
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for item in files[max_files:]:
                try:
                    item.unlink()
                    deleted += 1
                except OSError:
                    continue

    return deleted
