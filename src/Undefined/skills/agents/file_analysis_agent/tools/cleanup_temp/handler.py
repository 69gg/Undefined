from typing import Any, Dict
import logging
from pathlib import Path

from Undefined.skills.shared import (
    delete_download_cache_directory,
    download_cache_root,
    resolve_download_cache_path,
)

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """清理系统生成的临时文件和缓存"""
    task_uuid: str = args.get("task_uuid", "")

    cache_dir = download_cache_root(context)

    if not cache_dir.exists():
        return "下载缓存目录不存在"

    try:
        if task_uuid:
            if (
                task_uuid in {".", ".."}
                or Path(task_uuid).name != task_uuid
                or "\\" in task_uuid
            ):
                return "错误：task_uuid 必须是下载缓存的直接子目录名"
            target_dir = cache_dir / task_uuid
            if target_dir.is_symlink():
                return "错误：不能清理符号链接目录"
            target_dir = resolve_download_cache_path(target_dir, context)
            if target_dir.exists():
                await delete_download_cache_directory(target_dir)
                return f"已清理下载缓存目录: {target_dir}"
            else:
                return f"下载缓存目录不存在: {target_dir}"
        else:
            count = 0
            for item in cache_dir.iterdir():
                if item.is_dir() and not item.is_symlink():
                    target_dir = resolve_download_cache_path(item, context)
                    await delete_download_cache_directory(target_dir)
                    count += 1
            return f"已清理 {count} 个下载缓存目录"

    except ValueError as exc:
        return f"错误：{exc}"
    except Exception as e:
        logger.exception(f"清理下载缓存目录失败: {e}")
        return "清理下载缓存目录失败，请稍后重试"
