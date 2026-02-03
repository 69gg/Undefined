from typing import Any, Dict
from datetime import datetime


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取当前系统时间（格式：YYYY-MM-DD HH:MM:SS）"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
