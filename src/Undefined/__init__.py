"""Undefined - A high-performance, highly scalable QQ group and private chat robot based on a self-developed architecture."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ai import AIClient as AIClient
    from .api._context import RuntimeAPIContext as RuntimeAPIContext
    from .api.app import RuntimeAPIServer as RuntimeAPIServer
    from .attachments import AttachmentRegistry as AttachmentRegistry
    from .cognitive.service import CognitiveService as CognitiveService
    from .config import Config as Config
    from .config import get_config as get_config
    from .config import set_config as set_config
    from .knowledge.manager import KnowledgeManager as KnowledgeManager
    from .memes.service import MemeService as MemeService
    from .skills.agents import AgentRegistry as AgentRegistry
    from .skills.anthropic_skills import (
        AnthropicSkillRegistry as AnthropicSkillRegistry,
    )
    from .skills.pipelines.registry import PipelineRegistry as PipelineRegistry
    from .skills.registry import BaseRegistry as BaseRegistry
    from .skills.tools import ToolRegistry as ToolRegistry

__version__: str = "3.7.0"

# symbol -> (module_path, attribute_name)；首次访问时才 importlib 加载
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "Config": ("Undefined.config", "Config"),
    "get_config": ("Undefined.config", "get_config"),
    "set_config": ("Undefined.config", "set_config"),
    "AIClient": ("Undefined.ai", "AIClient"),
    "ToolRegistry": ("Undefined.skills.tools", "ToolRegistry"),
    "AgentRegistry": ("Undefined.skills.agents", "AgentRegistry"),
    "PipelineRegistry": ("Undefined.skills.pipelines.registry", "PipelineRegistry"),
    "BaseRegistry": ("Undefined.skills.registry", "BaseRegistry"),
    "AnthropicSkillRegistry": (
        "Undefined.skills.anthropic_skills",
        "AnthropicSkillRegistry",
    ),
    "CognitiveService": ("Undefined.cognitive.service", "CognitiveService"),
    "KnowledgeManager": ("Undefined.knowledge.manager", "KnowledgeManager"),
    "MemeService": ("Undefined.memes.service", "MemeService"),
    "AttachmentRegistry": ("Undefined.attachments", "AttachmentRegistry"),
    "RuntimeAPIServer": ("Undefined.api.app", "RuntimeAPIServer"),
    "RuntimeAPIContext": ("Undefined.api._context", "RuntimeAPIContext"),
}

__all__ = ["__version__", *_LAZY_IMPORTS]


def __getattr__(name: str) -> Any:
    if name not in _LAZY_IMPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, attr = _LAZY_IMPORTS[name]
    module = importlib.import_module(module_path)
    value = getattr(module, attr)
    globals()[name] = value
    return value
