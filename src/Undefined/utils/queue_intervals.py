from __future__ import annotations

from typing import Iterable

from Undefined.config import Config


def build_model_queue_intervals(config: Config) -> dict[str, float]:
    pairs: Iterable[tuple[str, float]] = (
        (config.chat_model.model_name, config.chat_model.queue_interval_seconds),
        (config.agent_model.model_name, config.agent_model.queue_interval_seconds),
        (config.vision_model.model_name, config.vision_model.queue_interval_seconds),
        (
            config.security_model.model_name,
            config.security_model.queue_interval_seconds,
        ),
    )
    intervals: dict[str, float] = {}
    for model_name, interval in pairs:
        name = str(model_name).strip()
        if not name:
            continue
        intervals[name] = float(interval)

    # 注册 pool 中模型的队列间隔
    for pool_source in (config.chat_model, config.agent_model):
        if pool_source.pool and pool_source.pool.enabled:
            for entry in pool_source.pool.models:
                name = entry.model_name.strip()
                if name and name not in intervals:
                    intervals[name] = float(entry.queue_interval_seconds)

    return intervals
