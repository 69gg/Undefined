"""定时任务持久化存储模块"""

import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 任务数据存储路径
TASKS_FILE_PATH = Path("data/scheduled_tasks.json")


@dataclass
class ToolCall:
    """工具调用配置"""

    tool_name: str
    tool_args: Dict[str, Any]


@dataclass
class ScheduledTask:
    """定时任务数据模型"""

    task_id: str
    tool_name: str  # 保留用于向后兼容
    tool_args: Dict[str, Any]  # 保留用于向后兼容
    cron: str
    target_id: Optional[int]
    target_type: str
    task_name: str
    max_executions: Optional[int]
    current_executions: int = 0
    created_at: str = ""
    context_id: Optional[str] = None
    # 新增字段：多工具调用支持
    tools: Optional[list[ToolCall]] = None
    execution_mode: str = "serial"  # serial: 串行执行, parallel: 并行执行

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        # 将 ToolCall 对象转换为字典
        if self.tools:
            result["tools"] = [tool.__dict__ for tool in self.tools]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduledTask":
        """从字典创建实例"""
        # 处理 tools 字段
        tools = None
        if "tools" in data and data["tools"]:
            tools = [ToolCall(**tool) for tool in data["tools"]]

        # 兼容旧格式：如果没有 tools 字段但有 tool_name，创建单工具列表
        if tools is None and "tool_name" in data and data["tool_name"]:
            tools = [
                ToolCall(
                    tool_name=data["tool_name"], tool_args=data.get("tool_args", {})
                )
            ]

        # 设置默认执行模式
        execution_mode = data.get("execution_mode", "serial")

        # 移除 tools 和 execution_mode，避免传递给 __init__
        data_copy = {
            k: v for k, v in data.items() if k not in ["tools", "execution_mode"]
        }

        return cls(**data_copy, tools=tools, execution_mode=execution_mode)


class ScheduledTaskStorage:
    """定时任务存储管理器"""

    def __init__(self) -> None:
        """初始化存储"""
        self._load()

    def _load(self) -> Dict[str, ScheduledTask]:
        """从文件加载所有任务"""
        if not TASKS_FILE_PATH.exists():
            return {}

        try:
            with open(TASKS_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                task_id: ScheduledTask.from_dict(task_data)
                for task_id, task_data in data.items()
            }
        except Exception as e:
            logger.error(f"加载定时任务数据失败: {e}")
            return {}

    async def save_all(self, tasks: Dict[str, Any]) -> None:
        """保存所有任务到文件"""
        try:
            # 确保保存的是基础类型字典
            data_to_save = {}
            for task_id, task_info in tasks.items():
                if isinstance(task_info, ScheduledTask):
                    data_to_save[task_id] = task_info.to_dict()
                elif isinstance(task_info, dict):
                    # 兼容 TaskScheduler 内部的 dict 格式
                    data_to_save[task_id] = task_info
                else:
                    logger.warning(f"未知任务数据格式: {task_id}")

            from Undefined.utils import io

            await io.write_json(TASKS_FILE_PATH, data_to_save, use_lock=True)
            logger.debug(f"已保存 {len(data_to_save)} 个定时任务")
        except Exception as e:
            logger.error(f"保存定时任务数据失败: {e}")

    def load_tasks(self) -> Dict[str, Any]:
        """读取所有任务（返回原始字典格式以适配现有代码）"""
        tasks = self._load()
        return {task_id: task.to_dict() for task_id, task in tasks.items()}
