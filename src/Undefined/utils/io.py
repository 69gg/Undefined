"""异步安全的 IO 工具模块"""

import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from Undefined.utils.file_lock import FileLock

logger = logging.getLogger(__name__)


async def write_json(file_path: Path | str, data: Any, use_lock: bool = True) -> None:
    """异步安全地写入 JSON 文件

    参数:
        file_path: 文件路径
        data: 要写入的数据
        use_lock: 是否使用文件锁确保并发安全
    """
    p = Path(file_path)
    start_time = time.perf_counter()

    # 估算数据大小
    data_size = len(str(data))
    logger.debug(
        f"[IO] 写入JSON: path={p}, use_lock={use_lock}, size_estimate={data_size} chars"
    )

    def lock_path_for(target: Path) -> Path:
        return target.with_name(f"{target.name}.lock")

    def sync_write() -> None:
        p.parent.mkdir(parents=True, exist_ok=True)

        def atomic_write() -> None:
            tmp_path: Path | None = None
            try:
                fd, tmp_name = tempfile.mkstemp(
                    prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent)
                )
                tmp_path = Path(tmp_name)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_name, p)
            finally:
                if tmp_path is not None and tmp_path.exists():
                    tmp_path.unlink()

        if use_lock:
            lock_path = lock_path_for(p)
            logger.debug(f"[IO] 获取排他锁: path={lock_path}")
            with FileLock(lock_path, shared=False):
                atomic_write()
            logger.debug(f"[IO] 释放锁: path={lock_path}")
        else:
            atomic_write()

    try:
        await asyncio.to_thread(sync_write)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[IO] 写入成功: path={p}, elapsed={elapsed:.3f}s")
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        logger.error(f"[IO] 写入失败: path={p}, elapsed={elapsed:.3f}s, error={e}")
        raise


async def read_json(file_path: Path | str, use_lock: bool = False) -> Optional[Any]:
    """异步安全地读取 JSON 文件

    参数:
        file_path: 文件路径
        use_lock: 是否使用共享锁读取

    返回:
        解析后的 JSON 数据，如果文件不存在则返回 None
    """
    p = Path(file_path)
    start_time = time.perf_counter()

    logger.debug(f"[IO] 读取JSON: path={p}, use_lock={use_lock}")

    def lock_path_for(target: Path) -> Path:
        return target.with_name(f"{target.name}.lock")

    def sync_read() -> Optional[Any]:
        if not p.exists():
            logger.debug(f"[IO] 文件不存在: path={p}")
            return None
        if use_lock:
            lock_path = lock_path_for(p)
            logger.debug(f"[IO] 获取共享锁: path={lock_path}")
            with FileLock(lock_path, shared=True):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            logger.debug(f"[IO] 释放锁: path={lock_path}")
            return data
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    try:
        result = await asyncio.to_thread(sync_read)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[IO] 读取成功: path={p}, elapsed={elapsed:.3f}s")
        return result
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        logger.error(f"[IO] 读取失败: path={p}, elapsed={elapsed:.3f}s, error={e}")
        raise


async def append_line(
    file_path: Path | str,
    line: str,
    use_lock: bool = True,
    lock_file_path: Path | str | None = None,
) -> None:
    """异步安全地向文件追加一行

    参数:
        file_path: 文件路径
        line: 要追加的内容（会自动添加换行符）
        use_lock: 是否使用文件锁
    """
    p = Path(file_path)
    start_time = time.perf_counter()

    if not line.endswith("\n"):
        line += "\n"

    logger.debug(f"[IO] 追加行: path={p}, use_lock={use_lock}, line_length={len(line)}")

    def lock_path_for(target: Path) -> Path:
        return target.with_name(f"{target.name}.lock")

    def sync_append() -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        lock_path = Path(lock_file_path) if lock_file_path else lock_path_for(p)
        if use_lock:
            logger.debug(f"[IO] 获取排他锁: path={lock_path}")
            with FileLock(lock_path, shared=False):
                with open(p, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
            logger.debug(f"[IO] 释放锁: path={lock_path}")
            return
        with open(p, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()

    try:
        await asyncio.to_thread(sync_append)
        elapsed = time.perf_counter() - start_time
        logger.info(f"[IO] 追加成功: path={p}, elapsed={elapsed:.3f}s")
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        logger.error(f"[IO] 追加失败: path={p}, elapsed={elapsed:.3f}s, error={e}")
        raise


async def exists(file_path: Path | str) -> bool:
    """异步检查文件或目录是否存在

    参数:
        file_path: 要检查的路径
    """
    return await asyncio.to_thread(Path(file_path).exists)


async def delete_file(file_path: Path | str) -> bool:
    """异步删除指定文件

    参数:
        file_path: 文件路径

    返回:
        删除成功返回 True，文件不存在则返回 False
    """
    p = Path(file_path)

    def sync_delete() -> bool:
        if p.exists():
            p.unlink()
            return True
        return False

    return await asyncio.to_thread(sync_delete)


def _write_text_sync(target: Path, content: str, use_lock: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)

    def atomic_write() -> None:
        tmp_path: Path | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
            )
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, target)
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink()

    if use_lock:
        lock_path = target.with_name(f"{target.name}.lock")
        with FileLock(lock_path, shared=False):
            atomic_write()
    else:
        atomic_write()


def _read_text_sync(target: Path, use_lock: bool) -> str | None:
    if not target.exists():
        return None
    if use_lock:
        lock_path = target.with_name(f"{target.name}.lock")
        with FileLock(lock_path, shared=True):
            return target.read_text(encoding="utf-8")
    return target.read_text(encoding="utf-8")


async def write_text(
    file_path: str | Path, content: str, use_lock: bool = True
) -> None:
    """原子写入文本文件"""
    target = Path(file_path)
    await asyncio.to_thread(_write_text_sync, target, content, use_lock)


async def read_text(file_path: str | Path, use_lock: bool = False) -> str | None:
    """异步读取文本文件"""
    target = Path(file_path)
    return await asyncio.to_thread(_read_text_sync, target, use_lock)
