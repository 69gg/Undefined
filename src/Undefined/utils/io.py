"""异步安全的 IO 工具模块"""

import asyncio
import json
import logging
import fcntl
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def write_json(file_path: Path | str, data: Any, use_lock: bool = True) -> None:
    """异步安全地写入 JSON 文件

    参数:
        file_path: 文件路径
        data: 要写入的数据
        use_lock: 是否使用文件锁确保并发安全
    """
    p = Path(file_path)

    def sync_write() -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        # 用 "w" 模式打开
        with open(p, "w", encoding="utf-8") as f:
            if use_lock:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(data, f, ensure_ascii=False, indent=2)
                # 显式刷新到磁盘
                f.flush()
            finally:
                if use_lock:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    await asyncio.to_thread(sync_write)


async def read_json(file_path: Path | str, use_lock: bool = False) -> Optional[Any]:
    """异步安全地读取 JSON 文件

    参数:
        file_path: 文件路径
        use_lock: 是否使用共享锁读取

    返回:
        解析后的 JSON 数据，如果文件不存在则返回 None
    """
    p = Path(file_path)

    def sync_read() -> Optional[Any]:
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            if use_lock:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                if use_lock:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    return await asyncio.to_thread(sync_read)


async def append_line(file_path: Path | str, line: str, use_lock: bool = True) -> None:
    """异步安全地向文件追加一行

    参数:
        file_path: 文件路径
        line: 要追加的内容（会自动添加换行符）
        use_lock: 是否使用文件锁
    """
    p = Path(file_path)
    if not line.endswith("\n"):
        line += "\n"

    def sync_append() -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            if use_lock:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(line)
                f.flush()
            finally:
                if use_lock:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    await asyncio.to_thread(sync_append)


async def exists(file_path: Path | str) -> bool:
    """异步检查文件是否存在"""
    return await asyncio.to_thread(Path(file_path).exists)


async def delete_file(file_path: Path | str) -> bool:
    """异步删除文件"""
    p = Path(file_path)

    def sync_delete() -> bool:
        if p.exists():
            p.unlink()
            return True
        return False

    return await asyncio.to_thread(sync_delete)
