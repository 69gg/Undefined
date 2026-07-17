from __future__ import annotations

import asyncio
import gzip
import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import Undefined.token_usage_storage as storage_module
from Undefined.token_usage_storage import TokenUsage, TokenUsageStorage
from Undefined.utils import io as async_io


def _usage_record(
    timestamp: datetime, model: str, total_tokens: int
) -> dict[str, object]:
    return {
        "timestamp": timestamp.isoformat(),
        "model_name": model,
        "prompt_tokens": total_tokens - 2,
        "completion_tokens": 2,
        "total_tokens": total_tokens,
        "duration_seconds": 1.5,
        "call_type": "chat",
        "success": True,
    }


async def _write_gzip_records(
    path: Path,
    records: list[dict[str, object]],
) -> None:
    def write() -> None:
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    await asyncio.to_thread(write)


@pytest.mark.asyncio
async def test_summary_streams_relevant_files_and_skips_old_archives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now()
    storage = TokenUsageStorage(tmp_path / "token_usage.jsonl")
    old_archive = storage.archive_dir / (
        f"token_usage.{(now - timedelta(days=30)).strftime('%Y%m%d-%H%M%S')}.jsonl.gz"
    )
    recent_archive = storage.archive_dir / (
        f"token_usage.{now.strftime('%Y%m%d-%H%M%S')}.jsonl.gz"
    )
    await _write_gzip_records(
        old_archive,
        [_usage_record(now - timedelta(days=31), "old", 999)],
    )
    await _write_gzip_records(
        recent_archive,
        [_usage_record(now - timedelta(days=2), "model-a", 30)],
    )
    current_records = [
        _usage_record(now - timedelta(hours=1), "model-b", 20),
        _usage_record(now - timedelta(days=20), "old-current", 100),
    ]
    await async_io.write_text(
        storage.file_path,
        "".join(json.dumps(record) + "\n" for record in current_records),
    )

    original_iter = storage_module._iter_usage_records

    def guarded_iter(path: Path) -> Iterator[TokenUsage]:
        if path == old_archive:
            raise AssertionError("old archive should not be scanned")
        yield from original_iter(path)

    monkeypatch.setattr(storage_module, "_iter_usage_records", guarded_iter)

    summary = await storage.get_summary(days=7)

    assert summary["total_calls"] == 2
    assert summary["total_tokens"] == 50
    assert summary["prompt_tokens"] == 46
    assert summary["completion_tokens"] == 4
    assert summary["avg_duration"] == 1.5
    assert summary["models"]["model-a"]["tokens"] == 30
    assert summary["models"]["model-b"]["tokens"] == 20
    assert summary["call_types"] == {"chat": 2}


def test_archive_upper_bound_uses_merged_timestamp(tmp_path: Path) -> None:
    storage = TokenUsageStorage(tmp_path / "token_usage.jsonl")

    upper_bound = storage._archive_upper_bound(
        storage.archive_dir
        / "token_usage.20260101-010203-merged.20260717-040506-2.jsonl.gz"
    )

    assert upper_bound == datetime(2026, 7, 17, 4, 5, 6)
