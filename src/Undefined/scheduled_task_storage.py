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
class ScheduledTask:
    """定时任务数据模型"""

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

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduledTask":
        """从字典创建实例"""
        return cls(**data)


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

    def save_all(self, tasks: Dict[str, Any]) -> None:
        """保存所有任务到文件"""
        try:
            TASKS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)

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

            with open(TASKS_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(data_to_save, f, ensure_ascii=False, indent=2)
            logger.debug(f"已保存 {len(data_to_save)} 个定时任务")
        except Exception as e:
            logger.error(f"保存定时任务数据失败: {e}")

    def load_tasks(self) -> Dict[str, Any]:
        """读取所有任务（返回原始字典格式以适配现有代码）"""
        tasks = self._load()
        return {task_id: task.to_dict() for task_id, task in tasks.items()}
