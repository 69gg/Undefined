"""定时任务 / 自动化持久化存储模块"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from Undefined.automations.storage import AutomationStorage

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """工具调用配置"""

    tool_name: str
    tool_args: Dict[str, Any]


@dataclass
class ScheduledTask:
    """定时任务数据模型（兼容旧字段；新图存在 nodes/edges 中）"""

    task_id: str
    tool_name: str
    tool_args: Dict[str, Any]
    cron: str
    target_id: Optional[int]
    target_type: str
    task_name: str
    max_executions: Optional[int]
    current_executions: int = 0
    created_at: str = ""
    context_id: Optional[str] = None
    address: Optional[str] = None
    tools: Optional[list[ToolCall]] = None
    execution_mode: str = "serial"
    self_instruction: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        if self.tools:
            result["tools"] = [tool.__dict__ for tool in self.tools]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduledTask":
        tools = None
        if "tools" in data and data["tools"]:
            tools = [
                ToolCall(**tool) for tool in data["tools"] if isinstance(tool, dict)
            ]

        if tools is None and "tool_name" in data and data["tool_name"]:
            tools = [
                ToolCall(
                    tool_name=data["tool_name"], tool_args=data.get("tool_args", {})
                )
            ]

        execution_mode = data.get("execution_mode", "serial")
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        data_copy = {
            key: value
            for key, value in data.items()
            if key in allowed and key not in {"tools", "execution_mode"}
        }
        return cls(**data_copy, tools=tools, execution_mode=execution_mode)


class ScheduledTaskStorage:
    """任务存储：启动时若无 automations.json 则读取旧 scheduled_tasks.json 转为新格式。"""

    def __init__(self) -> None:
        self._backend = AutomationStorage()
        self._tasks = self._load()

    def _load(self) -> Dict[str, ScheduledTask]:
        raw = self._backend.load_tasks()
        loaded: Dict[str, ScheduledTask] = {}
        for task_id, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            try:
                loaded[task_id] = ScheduledTask.from_dict(payload)
            except Exception:
                # 新图可能缺少旧必填字段；仍由 TaskScheduler 以 dict 持有
                continue
        return loaded

    async def save_all(self, tasks: Dict[str, Any]) -> None:
        await self._backend.save_all(tasks)

    def load_tasks(self) -> Dict[str, Any]:
        return self._backend.load_tasks()
