"""Token 使用统计存储模块

用于记录和查询 AI API 调用的 token 使用情况
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import aiofiles
import fcntl

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
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """确保存储文件存在"""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.touch()

    async def record(self, usage: TokenUsage) -> None:
        """记录一次 token 使用

        参数:
            usage: Token 使用记录
        """
        try:
            # 使用文件锁确保并发写入安全
            async with aiofiles.open(self.file_path, mode="a", encoding="utf-8") as f:
                # 获取文件锁
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    # 追加 JSON 行
                    line = json.dumps(usage.to_dict(), ensure_ascii=False) + "\n"
                    await f.write(line)
                finally:
                    # 释放文件锁
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            logger.debug(
                f"[Token统计] 已记录: {usage.call_type} - "
                f"{usage.model_name} - {usage.total_tokens} tokens"
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
            async with aiofiles.open(self.file_path, mode="r", encoding="utf-8") as f:
                async for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            records.append(TokenUsage.from_dict(data))
                        except json.JSONDecodeError:
                            logger.warning(f"[Token统计] 跳过无效行: {line}")
        except FileNotFoundError:
            logger.info(f"[Token统计] 文件不存在: {self.file_path}")
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
