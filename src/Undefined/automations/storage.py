"""Persist automations; one-way migrate from scheduled_tasks.json on first load."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from Undefined.automations.constants import (
    AUTOMATIONS_FILE_PATH,
    LEGACY_TASKS_FILE_PATH,
)
from Undefined.automations.migrate import migrate_legacy_task

logger = logging.getLogger(__name__)


class AutomationStorage:
    """Load/save automation graphs as JSON."""

    def __init__(
        self,
        path: Path | None = None,
        legacy_path: Path | None = None,
    ) -> None:
        self.path = path or AUTOMATIONS_FILE_PATH
        self.legacy_path = legacy_path or LEGACY_TASKS_FILE_PATH

    def load_tasks(self) -> dict[str, Any]:
        loaded_from_legacy = False
        if self.path.exists():
            raw = self._read_json(self.path) or {}
        else:
            raw = self._read_json(self.legacy_path) or {}
            loaded_from_legacy = self.legacy_path.exists()
        tasks: dict[str, Any] = {}
        if not isinstance(raw, dict):
            return tasks
        for task_id, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            try:
                tasks[str(task_id)] = migrate_legacy_task(payload)
            except Exception as exc:
                logger.error("[自动化] 加载任务失败 %s: %s", task_id, exc)
        if loaded_from_legacy and not self.path.exists():
            self._write_json_sync(self.path, tasks)
            logger.info(
                "[自动化] 已从 scheduled_tasks.json 转为新格式 %s 条，写入 %s（未删除旧文件）",
                len(tasks),
                self.path,
            )
        return tasks

    async def save_all(self, tasks: dict[str, Any]) -> None:
        from Undefined.utils import io

        data_to_save: dict[str, Any] = {}
        for task_id, task_info in tasks.items():
            if isinstance(task_info, dict):
                data_to_save[str(task_id)] = task_info
            else:
                logger.warning("[自动化] 跳过未知任务格式: %s", task_id)
        await io.write_json(self.path, data_to_save, use_lock=True)
        logger.debug("[自动化] 已保存 %s 条", len(data_to_save))

    def _write_json_sync(self, path: Path, data: dict[str, Any]) -> None:
        from Undefined.utils.io import write_json_sync

        write_json_sync(path, data, use_lock=True)

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            import json

            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except Exception as exc:
            logger.error("[自动化] 读取 %s 失败: %s", path, exc)
            return None
