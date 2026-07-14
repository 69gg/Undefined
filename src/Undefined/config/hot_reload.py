from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from Undefined.ai import AIClient
from Undefined.config import Config
from Undefined.config.manager import ConfigManager
from Undefined.services.security import SecurityService
from Undefined.services.queue_manager import QueueManager
from Undefined.skills.agents.intro_generator import AgentIntroGenConfig
from Undefined.utils.queue_intervals import build_model_queue_intervals

if TYPE_CHECKING:
    from Undefined.handlers import MessageHandler

logger = logging.getLogger(__name__)


_RESTART_REQUIRED_KEYS: set[str] = {
    "log_level",
    "log_file_path",
    "log_max_size",
    "log_backup_count",
    "log_tty_enabled",
    "onebot_ws_url",
    "onebot_token",
    "webui_url",
    "webui_port",
    "webui_password",
    "webui_autostart_bot",
    "render_browser_executable_path",
    "api",
    "api.enabled",
    "api.host",
    "api.port",
    "api.auth_key",
    "api.openapi_enabled",
    "naga",
}

_QUEUE_INTERVAL_KEYS: set[str] = {
    "chat_model.queue_interval_seconds",
    "vision_model.queue_interval_seconds",
    "security_model.queue_interval_seconds",
    "naga_model.queue_interval_seconds",
    "agent_model.queue_interval_seconds",
    "summary_model.queue_interval_seconds",
    "historian_model.queue_interval_seconds",
    "grok_model.queue_interval_seconds",
    "chat_model.pool",
    "agent_model.pool",
}

_MODEL_NAME_KEYS: set[str] = {
    "chat_model.model_name",
    "vision_model.model_name",
    "security_model.model_name",
    "naga_model.model_name",
    "agent_model.model_name",
    "summary_model.model_name",
    "historian_model.model_name",
    "grok_model.model_name",
}

_CORE_AI_MODEL_CONFIG_PREFIXES: tuple[str, ...] = (
    "chat_model",
    "vision_model",
    "agent_model",
)

_RUNTIME_AI_MODEL_CONFIG_PREFIXES: tuple[str, ...] = (
    "summary_model",
    "historian_model",
    "grok_model",
    "missing_tool_call_retries",
    "tool_search_enabled",
    "tool_search_always_loaded",
    "tool_search_max_results",
    "render_long_image_default_width",
    "render_long_image_default_padding",
)

_AGENT_INTRO_KEYS: set[str] = {
    "agent_intro_autogen_enabled",
    "agent_intro_autogen_queue_interval",
    "agent_intro_autogen_max_tokens",
    "agent_intro_hash_path",
}

_SKILLS_HOT_RELOAD_KEYS: set[str] = {
    "skills_hot_reload",
    "skills_hot_reload_interval",
    "skills_hot_reload_debounce",
}

_CONFIG_HOT_RELOAD_KEYS: set[str] = {
    "skills_hot_reload_interval",
    "skills_hot_reload_debounce",
}

_SEARCH_KEYS: set[str] = {"searxng_url"}

_ATTACHMENT_KEYS: set[str] = {
    "attachment_remote_download_max_size_mb",
    "attachment_cache_max_total_size_mb",
    "attachment_cache_max_records",
    "attachment_cache_max_age_days",
    "attachment_url_reference_max_records",
    "attachment_url_max_length",
}

_MESSAGE_BATCHER_KEYS: set[str] = {
    "message_batcher",
    "message_batcher.enabled",
    "message_batcher.window_seconds",
    "message_batcher.strategy",
    "message_batcher.max_window_seconds",
    "message_batcher.max_messages_per_batch",
    "message_batcher.group_enabled",
    "message_batcher.private_enabled",
    "message_batcher.flush_on_command",
}


@dataclass
class HotReloadContext:
    ai_client: AIClient
    queue_manager: QueueManager
    config_manager: ConfigManager
    security_service: SecurityService
    message_handler: MessageHandler | None = None


def apply_config_updates(
    updated: Config,
    changes: dict[str, tuple[object, object]],
    context: HotReloadContext,
) -> None:
    if not changes:
        return

    changed_keys = set(changes.keys())
    logger.debug("[配置] 热更新变更项: %s", ", ".join(sorted(changed_keys)))
    _log_restart_required(changed_keys)
    context.security_service.apply_config(updated)
    if "ai_request_max_retries" in changed_keys:
        context.queue_manager.update_max_retries(updated.ai_request_max_retries)

    if _needs_queue_interval_update(changed_keys):
        context.queue_manager.update_model_intervals(
            build_model_queue_intervals(updated)
        )

    if _needs_intro_update(changed_keys):
        intro_config = AgentIntroGenConfig(
            enabled=updated.agent_intro_autogen_enabled,
            queue_interval_seconds=updated.agent_intro_autogen_queue_interval,
            max_tokens=updated.agent_intro_autogen_max_tokens,
            cache_path=Path(updated.agent_intro_hash_path),
        )
        context.ai_client.apply_intro_config(intro_config)

    if _needs_search_update(changed_keys):
        context.ai_client.apply_search_config(updated.searxng_url)

    if _needs_attachment_update(changed_keys):
        context.ai_client.apply_attachment_config(updated)

    if _needs_message_batcher_update(changed_keys):
        handler = context.message_handler
        if (
            handler is not None
            and getattr(handler, "message_batcher", None) is not None
        ):
            handler.message_batcher.update_config(updated.message_batcher)

    if _needs_core_ai_model_update(changed_keys):
        context.ai_client.apply_model_configs(
            chat_config=updated.chat_model,
            vision_config=updated.vision_model,
            agent_config=updated.agent_model,
            runtime_config=updated,
        )
    elif _needs_runtime_ai_model_update(changed_keys):
        context.ai_client.apply_runtime_config(updated)

    if _needs_skills_hot_reload_update(changed_keys):
        asyncio.create_task(_apply_skills_hot_reload(updated, context.ai_client))
        asyncio.create_task(
            _apply_message_handler_skills_hot_reload(
                updated,
                context.message_handler,
            )
        )

    if _needs_config_hot_reload_update(changed_keys):
        asyncio.create_task(
            _restart_config_hot_reload(
                context.config_manager,
                updated.skills_hot_reload_interval,
                updated.skills_hot_reload_debounce,
            )
        )


def _log_restart_required(changed_keys: set[str]) -> None:
    hits = sorted(key for key in changed_keys if key in _RESTART_REQUIRED_KEYS)
    if hits:
        logger.warning("[配置] 以下配置变更需要重启生效: %s", ", ".join(hits))


def _needs_queue_interval_update(changed_keys: set[str]) -> bool:
    return bool(changed_keys & (_QUEUE_INTERVAL_KEYS | _MODEL_NAME_KEYS))


def _needs_intro_update(changed_keys: set[str]) -> bool:
    return bool(changed_keys & _AGENT_INTRO_KEYS)


def _needs_skills_hot_reload_update(changed_keys: set[str]) -> bool:
    return bool(changed_keys & _SKILLS_HOT_RELOAD_KEYS)


def _needs_config_hot_reload_update(changed_keys: set[str]) -> bool:
    return bool(changed_keys & _CONFIG_HOT_RELOAD_KEYS)


def _needs_search_update(changed_keys: set[str]) -> bool:
    return bool(changed_keys & _SEARCH_KEYS)


def _needs_attachment_update(changed_keys: set[str]) -> bool:
    return bool(changed_keys & _ATTACHMENT_KEYS)


def _needs_message_batcher_update(changed_keys: set[str]) -> bool:
    return any(
        key == "message_batcher" or key.startswith("message_batcher.")
        for key in changed_keys
    )


def _matches_prefixes(changed_keys: set[str], prefixes: tuple[str, ...]) -> bool:
    return any(
        key == prefix or key.startswith(f"{prefix}.")
        for key in changed_keys
        for prefix in prefixes
    )


def _needs_core_ai_model_update(changed_keys: set[str]) -> bool:
    return _matches_prefixes(changed_keys, _CORE_AI_MODEL_CONFIG_PREFIXES)


def _needs_runtime_ai_model_update(changed_keys: set[str]) -> bool:
    return _matches_prefixes(changed_keys, _RUNTIME_AI_MODEL_CONFIG_PREFIXES)


async def _apply_skills_hot_reload(updated: Config, ai_client: AIClient) -> None:
    registries: list[Any] = [ai_client.tool_registry, ai_client.agent_registry]
    anthropic_skill_registry = getattr(ai_client, "anthropic_skill_registry", None)
    if anthropic_skill_registry is not None:
        registries.append(anthropic_skill_registry)

    if not updated.skills_hot_reload:
        for registry in registries:
            await registry.stop_hot_reload()
        logger.info("[配置] 技能热重载已禁用")
        return

    for registry in registries:
        await registry.stop_hot_reload()
        registry.start_hot_reload(
            interval=updated.skills_hot_reload_interval,
            debounce=updated.skills_hot_reload_debounce,
        )
    logger.info(
        "[配置] 技能热重载已更新: interval=%.2fs debounce=%.2fs",
        updated.skills_hot_reload_interval,
        updated.skills_hot_reload_debounce,
    )


async def _apply_message_handler_skills_hot_reload(
    updated: Config,
    message_handler: MessageHandler | None,
) -> None:
    if message_handler is None:
        return
    await message_handler.apply_skills_hot_reload_config(
        enabled=updated.skills_hot_reload,
        interval=updated.skills_hot_reload_interval,
        debounce=updated.skills_hot_reload_debounce,
    )


async def _restart_config_hot_reload(
    config_manager: ConfigManager, interval: float, debounce: float
) -> None:
    await config_manager.stop_hot_reload()
    config_manager.start_hot_reload(interval=interval, debounce=debounce)
    logger.info(
        "[配置] 配置热更新已重启: interval=%.2fs debounce=%.2fs",
        interval,
        debounce,
    )
