"""Shared context types for the Runtime API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class RuntimeAPIContext:
    config_getter: Callable[[], Any]
    onebot: Any
    ai: Any
    command_dispatcher: Any
    queue_manager: Any
    history_manager: Any
    sender: Any = None
    scheduler: Any = None
    cognitive_service: Any = None
    cognitive_job_queue: Any = None
    meme_service: Any = None
    naga_store: Any = None
