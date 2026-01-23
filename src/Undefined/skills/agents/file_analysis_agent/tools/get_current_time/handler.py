from typing import Any, Dict
from datetime import datetime


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
