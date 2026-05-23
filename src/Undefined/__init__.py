"""Undefined - A high-performance, highly scalable QQ group and private chat robot based on a self-developed architecture."""

from __future__ import annotations

import importlib
from typing import Any

__version__ = "3.4.2"

__all__ = [
    "__version__",
    "Config",
    "get_config",
    "AIClient",
    "ToolRegistry",
    "AgentRegistry",
    "PipelineRegistry",
    "BaseRegistry",
    "AnthropicSkillRegistry",
    "CognitiveService",
    "KnowledgeManager",
    "MemeService",
    "AttachmentRegistry",
    "RuntimeAPIServer",
    "RuntimeAPIContext",
]

# symbol -> (module_path, attribute_name)；首次访问时才 importlib 加载
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "Config": ("Undefined.config", "Config"),
    "get_config": ("Undefined.config", "get_config"),
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


def __getattr__(name: str) -> Any:
    if name not in _LAZY_IMPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, attr = _LAZY_IMPORTS[name]
    module = importlib.import_module(module_path)
    value = getattr(module, attr)
    globals()[name] = value
    return value
