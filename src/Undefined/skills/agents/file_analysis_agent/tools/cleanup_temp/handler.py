from typing import Any, Dict
import logging
import shutil

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    task_uuid: str = args.get("task_uuid", "")

    from Undefined.utils.paths import DOWNLOAD_CACHE_DIR

    cache_dir = DOWNLOAD_CACHE_DIR

    if not cache_dir.exists():
        return "下载缓存目录不存在"

    try:
        if task_uuid:
            target_dir = cache_dir / task_uuid
            if target_dir.exists():
                shutil.rmtree(target_dir)
                return f"已清理下载缓存目录: {target_dir}"
            else:
                return f"下载缓存目录不存在: {target_dir}"
        else:
            count = 0
            for item in cache_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                    count += 1
            return f"已清理 {count} 个下载缓存目录"

    except Exception as e:
        logger.exception(f"清理下载缓存目录失败: {e}")
        return f"清理下载缓存目录失败: {e}"
