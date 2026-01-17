from pathlib import Path
from typing import Any, Dict
import logging
import shutil

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    task_uuid: str = args.get("task_uuid", "")

    temp_dir = Path.cwd() / "temp"

    if not temp_dir.exists():
        return "临时目录不存在"

    try:
        if task_uuid:
            target_dir = temp_dir / task_uuid
            if target_dir.exists():
                shutil.rmtree(target_dir)
                return f"已清理临时目录: {target_dir}"
            else:
                return f"临时目录不存在: {target_dir}"
        else:
            count = 0
            for item in temp_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                    count += 1
            return f"已清理 {count} 个临时目录"

    except Exception as e:
        logger.exception(f"清理临时目录失败: {e}")
        return f"清理临时目录失败: {e}"
