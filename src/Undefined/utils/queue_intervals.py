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
        (
            config.inflight_summary_model.model_name,
            config.inflight_summary_model.queue_interval_seconds,
        ),
    )
    intervals: dict[str, float] = {}
    for model_name, interval in pairs:
        name = str(model_name).strip()
        if not name:
            continue
        intervals[name] = float(interval)
    return intervals
