from typing import Any, Dict
from datetime import datetime


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取当前系统时间（格式：YYYY-MM-DDTHH:MM:SS(+|-)HH:MM）"""
    return datetime.now().astimezone().isoformat(timespec="seconds")
