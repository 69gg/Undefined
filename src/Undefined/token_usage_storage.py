"""Token 使用统计存储模块

用于记录和查询 AI API 调用的 token 使用情况
"""

import asyncio
import gzip
import json
import logging
import os
import shutil
import fcntl
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """单次 API 调用的 token 使用记录"""

    timestamp: str  # ISO 8601 格式时间戳
    model_name: str  # 模型名称
    prompt_tokens: int  # 输入 token 数
    completion_tokens: int  # 输出 token 数
    total_tokens: int  # 总 token 数
    duration_seconds: float  # 调用耗时（秒）
    call_type: str  # 调用类型（如 "chat", "vision", "agent", "security" 等）
    success: bool  # 是否成功

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TokenUsage":
        """从字典创建实例"""
        return cls(**data)


class TokenUsageStorage:
    """Token 使用统计存储管理器"""

    def __init__(self, file_path: Optional[Path] = None) -> None:
        """初始化存储管理器

        参数:
            file_path: 存储文件路径，默认为 data/token_usage.jsonl
        """
        if file_path is None:
            file_path = Path("data/token_usage.jsonl")

        self.file_path: Path = file_path
        self.archive_dir: Path = (
            self.file_path.parent / f"{self.file_path.stem}_archives"
        )
        self.lock_file_path: Path = self.file_path.with_name(
            f"{self.file_path.name}.lock"
        )
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """确保存储文件存在"""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.touch()
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        if not self.lock_file_path.exists():
            self.lock_file_path.touch()

    @staticmethod
    def _parse_env_int(name: str, default: int) -> int:
        value = os.getenv(name, str(default)).strip()
        try:
            return int(value)
        except ValueError:
            return default

    def _archive_prefix(self) -> str:
        return self.file_path.stem

    def _list_archives(self) -> list[Path]:
        pattern = f"{self._archive_prefix()}.*.jsonl.gz"
        candidates = sorted(
            self.archive_dir.glob(pattern),
            key=lambda path: path.name,
        )
        return [path for path in candidates if not path.name.endswith(".tmp")]

    def _build_archive_path(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base_name = f"{self._archive_prefix()}.{timestamp}.jsonl.gz"
        candidate = self.archive_dir / base_name
        index = 1
        while candidate.exists():
            candidate = self.archive_dir / (
                f"{self._archive_prefix()}.{timestamp}-{index}.jsonl.gz"
            )
            index += 1
        return candidate

    def _prune_archives(
        self, max_archives: Optional[int], max_total_bytes: Optional[int]
    ) -> None:
        archives = self._list_archives()
        logger.info(
            "[Token统计] 归档清理检查: count=%s max_archives=%s max_total_bytes=%s",
            len(archives),
            max_archives if max_archives is not None else "unlimited",
            max_total_bytes if max_total_bytes is not None else "unlimited",
        )
        if max_archives is not None and max_archives > 0:
            if len(archives) > max_archives:
                for path in archives[: len(archives) - max_archives]:
                    try:
                        path.unlink()
                        logger.info("[Token统计] 已删除归档(超数量): %s", path)
                    except Exception:
                        logger.warning(f"[Token统计] 无法删除归档: {path}")
                archives = self._list_archives()

        if max_total_bytes is not None and max_total_bytes > 0:
            total = 0
            sizes: list[tuple[Path, int]] = []
            for path in archives:
                try:
                    size = path.stat().st_size
                except FileNotFoundError:
                    continue
                sizes.append((path, size))
                total += size
            if total > max_total_bytes:
                for path, size in sizes:
                    try:
                        path.unlink()
                        total -= size
                        logger.info(
                            "[Token统计] 已删除归档(超总量): %s size=%s",
                            path,
                            size,
                        )
                    except Exception:
                        logger.warning(f"[Token统计] 无法删除归档: {path}")
                    if total <= max_total_bytes:
                        break

    async def compact_if_needed(
        self,
        max_size_bytes: Optional[int] = None,
        max_archives: Optional[int] = None,
        max_total_bytes: Optional[int] = None,
    ) -> bool:
        """当文件超过阈值时进行压缩归档，并按策略清理历史归档"""
        if max_size_bytes is None:
            max_size_mb = self._parse_env_int("TOKEN_USAGE_MAX_SIZE_MB", 3)
            if max_size_mb <= 0:
                return False
            max_size_bytes = max_size_mb * 1024 * 1024

        if max_archives is None:
            max_archives = self._parse_env_int("TOKEN_USAGE_MAX_ARCHIVES", 30)
            if max_archives <= 0:
                max_archives = None

        if max_total_bytes is None:
            max_total_mb = self._parse_env_int("TOKEN_USAGE_MAX_TOTAL_MB", 0)
            max_total_bytes = max_total_mb * 1024 * 1024 if max_total_mb > 0 else None

        def sync_compact() -> bool:
            self._ensure_file_exists()
            did_compact = False
            self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(
                "[Token统计] 归档检查: file=%s archive_dir=%s threshold_bytes=%s max_archives=%s max_total_bytes=%s",
                self.file_path,
                self.archive_dir,
                max_size_bytes,
                max_archives if max_archives is not None else "unlimited",
                max_total_bytes if max_total_bytes is not None else "unlimited",
            )
            with open(self.lock_file_path, "a", encoding="utf-8") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                try:
                    if not self.file_path.exists():
                        logger.info("[Token统计] 归档跳过: 文件不存在")
                        return False
                    try:
                        size = self.file_path.stat().st_size
                    except FileNotFoundError:
                        logger.info("[Token统计] 归档跳过: 文件状态不可用")
                        return False
                    logger.info(
                        "[Token统计] 当前文件大小: %s bytes (threshold=%s)",
                        size,
                        max_size_bytes,
                    )
                    if size >= max_size_bytes and size > 0:
                        archive_path = self._build_archive_path()
                        tmp_path = archive_path.with_suffix(
                            archive_path.suffix + ".tmp"
                        )
                        logger.info(
                            "[Token统计] 开始归档: %s -> %s",
                            self.file_path,
                            archive_path,
                        )
                        with open(self.file_path, "rb") as src:
                            with gzip.open(tmp_path, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                        tmp_path.replace(archive_path)
                        with open(self.file_path, "w", encoding="utf-8"):
                            pass
                        did_compact = True
                        logger.info("[Token统计] 归档完成: %s", archive_path)
                    else:
                        logger.info("[Token统计] 归档未触发: 文件未超过阈值")
                    self._prune_archives(max_archives, max_total_bytes)
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            return did_compact

        try:
            return await asyncio.to_thread(sync_compact)
        except Exception as e:
            logger.error(f"[Token统计] 压缩归档失败: {e}")
            return False

    async def record(self, usage: TokenUsage | dict[str, Any]) -> None:
        """记录一次 token 使用

        使用统一的 io 层执行异步写操作。

        参数:
            usage: Token 使用记录（TokenUsage 对象或字典）
        """
        try:
            # 转换为字典
            if isinstance(usage, TokenUsage):
                data = usage.to_dict()
            else:
                data = usage

            # 准备要写入的行
            line = json.dumps(data, ensure_ascii=False)

            # 使用统一 IO 层追加内容
            from Undefined.utils import io

            await io.append_line(
                self.file_path,
                line,
                use_lock=True,
                lock_file_path=self.lock_file_path,
            )

            logger.debug(
                f"[Token统计] 已记录: {data.get('call_type')} - "
                f"{data.get('model_name')} - {data.get('total_tokens')} tokens"
            )
        except Exception as e:
            logger.error(f"[Token统计] 记录失败: {e}")

    async def get_all_records(self) -> list[TokenUsage]:
        """获取所有记录

        返回:
            TokenUsage 记录列表
        """
        records: list[TokenUsage] = []
        try:

            def read_records_from_path(path: Path) -> list[TokenUsage]:
                batch: list[TokenUsage] = []
                if not path.exists():
                    return batch
                try:
                    if path.suffix == ".gz":
                        f_handle = gzip.open(path, "rt", encoding="utf-8")
                    else:
                        f_handle = open(path, "r", encoding="utf-8")
                    with f_handle as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    data = json.loads(line)
                                    batch.append(TokenUsage.from_dict(data))
                                except json.JSONDecodeError:
                                    pass
                except OSError:
                    logger.warning(f"[Token统计] 读取归档失败: {path}")
                return batch

            def sync_read() -> list[TokenUsage]:
                batch: list[TokenUsage] = []
                for archive in self._list_archives():
                    batch.extend(read_records_from_path(archive))
                batch.extend(read_records_from_path(self.file_path))
                return batch

            records = await asyncio.to_thread(sync_read)
        except Exception as e:
            logger.error(f"[Token统计] 读取失败: {e}")

        return records

    async def get_records_by_date_range(
        self, start_date: datetime, end_date: datetime
    ) -> list[TokenUsage]:
        """获取指定日期范围内的记录

        参数:
            start_date: 开始日期
            end_date: 结束日期

        返回:
            TokenUsage 记录列表
        """
        all_records = await self.get_all_records()
        filtered: list[TokenUsage] = []

        for record in all_records:
            try:
                record_time = datetime.fromisoformat(record.timestamp)
                if start_date <= record_time <= end_date:
                    filtered.append(record)
            except ValueError:
                logger.warning(f"[Token统计] 无效的时间戳: {record.timestamp}")
                continue

        return filtered

    async def get_stats_by_model(
        self, model_name: str, days: int = 7
    ) -> dict[str, Any]:
        """获取指定模型的统计信息

        参数:
            model_name: 模型名称
            days: 最近多少天

        返回:
            统计信息字典
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        records = await self.get_records_by_date_range(start_date, end_date)
        model_records = [r for r in records if r.model_name == model_name]

        if not model_records:
            return {
                "model_name": model_name,
                "total_calls": 0,
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "avg_duration": 0.0,
            }

        total_calls = len(model_records)
        total_tokens = sum(r.total_tokens for r in model_records)
        prompt_tokens = sum(r.prompt_tokens for r in model_records)
        completion_tokens = sum(r.completion_tokens for r in model_records)
        avg_duration = sum(r.duration_seconds for r in model_records) / total_calls

        return {
            "model_name": model_name,
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "avg_duration": avg_duration,
        }

    async def get_summary(self, days: int = 7) -> dict[str, Any]:
        """获取最近 N 天的汇总统计

        参数:
            days: 最近多少天

        返回:
            汇总统计字典
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        records = await self.get_records_by_date_range(start_date, end_date)

        if not records:
            return {
                "total_calls": 0,
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "avg_duration": 0.0,
                "models": {},
                "call_types": {},
                "daily_stats": {},
            }

        total_calls = len(records)
        total_tokens = sum(r.total_tokens for r in records)
        prompt_tokens = sum(r.prompt_tokens for r in records)
        completion_tokens = sum(r.completion_tokens for r in records)
        avg_duration = sum(r.duration_seconds for r in records) / total_calls

        # 按模型统计
        models: dict[str, dict[str, Any]] = {}
        for record in records:
            model = record.model_name
            if model not in models:
                models[model] = {
                    "calls": 0,
                    "tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                }
            models[model]["calls"] += 1
            models[model]["tokens"] += record.total_tokens
            models[model]["prompt_tokens"] += record.prompt_tokens
            models[model]["completion_tokens"] += record.completion_tokens

        # 按调用类型统计
        call_types: dict[str, int] = {}
        for record in records:
            call_type = record.call_type
            call_types[call_type] = call_types.get(call_type, 0) + 1

        # 按日期统计
        daily_stats: dict[str, dict[str, Any]] = {}
        for record in records:
            try:
                record_time = datetime.fromisoformat(record.timestamp)
                date_str = record_time.strftime("%Y-%m-%d")
                if date_str not in daily_stats:
                    daily_stats[date_str] = {
                        "calls": 0,
                        "tokens": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                    }
                daily_stats[date_str]["calls"] += 1
                daily_stats[date_str]["tokens"] += record.total_tokens
                daily_stats[date_str]["prompt_tokens"] += record.prompt_tokens
                daily_stats[date_str]["completion_tokens"] += record.completion_tokens
            except ValueError:
                continue

        return {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "avg_duration": avg_duration,
            "models": models,
            "call_types": call_types,
            "daily_stats": daily_stats,
        }
