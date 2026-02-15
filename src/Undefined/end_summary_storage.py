"""End 摘要持久化存储模块"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

from Undefined.utils.file_lock import FileLock

logger = logging.getLogger(__name__)

# End 摘要数据存储路径
END_SUMMARIES_FILE_PATH = Path("data/end_summaries.json")
MAX_END_SUMMARIES = 200


class EndSummaryRecord(TypedDict):
    """End 摘要记录。"""

    summary: str
    timestamp: str
    location: NotRequired["EndSummaryLocation"]


class EndSummaryLocation(TypedDict):
    """End 摘要存储位置。"""

    type: Literal["private", "group"]
    name: str


def _now_iso_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _lock_path_for(target: Path) -> Path:
    return target.with_name(f"{target.name}.lock")


class EndSummaryStorage:
    """End 摘要存储管理器"""

    def __init__(self) -> None:
        """初始化存储"""
        self._append_lock = asyncio.Lock()

    @staticmethod
    def _normalize_location(value: Any) -> EndSummaryLocation | None:
        if not isinstance(value, dict):
            return None

        location_type = value.get("type")
        if location_type not in {"private", "group"}:
            return None

        location_name_raw = value.get("name")
        if not isinstance(location_name_raw, str):
            return None

        location_name = location_name_raw.strip()
        if not location_name:
            return None

        return {"type": location_type, "name": location_name}

    @staticmethod
    def make_record(
        summary: str,
        timestamp: str | None = None,
        location: EndSummaryLocation | None = None,
    ) -> EndSummaryRecord:
        """构建单条摘要记录。"""
        resolved_timestamp = (timestamp or _now_iso_timestamp()).strip()
        if not resolved_timestamp:
            resolved_timestamp = _now_iso_timestamp()
        record: EndSummaryRecord = {
            "summary": summary.strip(),
            "timestamp": resolved_timestamp,
        }
        normalized_location = EndSummaryStorage._normalize_location(location)
        if normalized_location is not None:
            record["location"] = normalized_location
        return record

    def _normalize_records(self, data: Any) -> list[EndSummaryRecord]:
        """兼容旧格式并归一化为带时间戳记录。"""
        if data is None:
            return []

        if not isinstance(data, list):
            logger.warning("[End摘要] 数据格式异常，期望 list，实际=%s", type(data))
            return []

        normalized: list[EndSummaryRecord] = []
        for item in data:
            if isinstance(item, str):
                summary = item.strip()
                if summary:
                    normalized.append(self.make_record(summary))
                continue

            if isinstance(item, dict):
                summary_raw = item.get("summary")
                if not isinstance(summary_raw, str):
                    continue
                summary = summary_raw.strip()
                if not summary:
                    continue

                timestamp_raw = item.get("timestamp")
                timestamp = (
                    timestamp_raw.strip()
                    if isinstance(timestamp_raw, str) and timestamp_raw.strip()
                    else _now_iso_timestamp()
                )
                location = self._normalize_location(item.get("location"))
                normalized.append(
                    self.make_record(
                        summary=summary,
                        timestamp=timestamp,
                        location=location,
                    )
                )

        return normalized[-MAX_END_SUMMARIES:]

    async def save(self, summaries: list[EndSummaryRecord]) -> None:
        """保存所有摘要到文件。"""
        try:
            from Undefined.utils import io

            normalized = self._normalize_records(summaries)
            await io.write_json(END_SUMMARIES_FILE_PATH, normalized, use_lock=True)
            logger.debug(
                "[End摘要] 保存完成: count=%s file=%s",
                len(normalized),
                END_SUMMARIES_FILE_PATH,
            )
        except Exception as exc:
            logger.error("[End摘要] 保存失败: %s", exc)

    async def load(self) -> list[EndSummaryRecord]:
        """从文件加载所有摘要（异步）。"""
        from Undefined.utils import io

        data = await io.read_json(END_SUMMARIES_FILE_PATH, use_lock=False)
        return self._normalize_records(data)

    def _append_summary_sync(self, record: EndSummaryRecord) -> list[EndSummaryRecord]:
        """在同一把文件锁下执行读改写，避免并发丢记录。"""
        END_SUMMARIES_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        lock_path = _lock_path_for(END_SUMMARIES_FILE_PATH)

        with FileLock(lock_path, shared=False):
            existing_data: Any = None
            if END_SUMMARIES_FILE_PATH.exists():
                try:
                    with open(END_SUMMARIES_FILE_PATH, "r", encoding="utf-8") as file:
                        existing_data = json.load(file)
                except Exception as exc:
                    logger.warning("[End摘要] 读取现有数据失败，按空列表处理: %s", exc)
                    existing_data = []

            records = self._normalize_records(existing_data)
            records.append(record)
            records = records[-MAX_END_SUMMARIES:]

            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{END_SUMMARIES_FILE_PATH.name}.",
                suffix=".tmp",
                dir=str(END_SUMMARIES_FILE_PATH.parent),
            )
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    json.dump(records, file, ensure_ascii=False, indent=2)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(tmp_path, END_SUMMARIES_FILE_PATH)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()

            return records

    async def append_summary(
        self,
        summary: str,
        timestamp: str | None = None,
        location: EndSummaryLocation | None = None,
    ) -> EndSummaryRecord | None:
        """追加一条摘要并持久化，返回最终写入记录。"""
        cleaned_summary = summary.strip()
        if not cleaned_summary:
            return None

        record = self.make_record(cleaned_summary, timestamp, location=location)
        try:
            async with self._append_lock:
                await asyncio.to_thread(self._append_summary_sync, record)
            logger.debug(
                "[End摘要] 追加完成: summary=%s file=%s",
                cleaned_summary[:50],
                END_SUMMARIES_FILE_PATH,
            )
            return record
        except Exception as exc:
            logger.error("[End摘要] 追加失败: %s", exc)
            return None
