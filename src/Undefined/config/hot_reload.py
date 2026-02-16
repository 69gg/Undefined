from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from Undefined.ai import AIClient
from Undefined.config import Config
from Undefined.config.manager import ConfigManager
from Undefined.services.queue_manager import QueueManager
from Undefined.skills.agents.intro_generator import AgentIntroGenConfig
from Undefined.utils.queue_intervals import build_model_queue_intervals

logger = logging.getLogger(__name__)


_RESTART_REQUIRED_KEYS: set[str] = {
    "ai_request_max_retries",
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
}

_QUEUE_INTERVAL_KEYS: set[str] = {
    "chat_model.queue_interval_seconds",
    "vision_model.queue_interval_seconds",
    "security_model.queue_interval_seconds",
    "agent_model.queue_interval_seconds",
}

_MODEL_NAME_KEYS: set[str] = {
    "chat_model.model_name",
    "vision_model.model_name",
    "security_model.model_name",
    "agent_model.model_name",
}

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


@dataclass
class HotReloadContext:
    ai_client: AIClient
    queue_manager: QueueManager
    config_manager: ConfigManager


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

    if _needs_skills_hot_reload_update(changed_keys):
        asyncio.create_task(_apply_skills_hot_reload(updated, context.ai_client))

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


async def _apply_skills_hot_reload(updated: Config, ai_client: AIClient) -> None:
    if not updated.skills_hot_reload:
        await ai_client.tool_registry.stop_hot_reload()
        await ai_client.agent_registry.stop_hot_reload()
        logger.info("[配置] 技能热重载已禁用")
        return

    await ai_client.tool_registry.stop_hot_reload()
    await ai_client.agent_registry.stop_hot_reload()
    ai_client.tool_registry.start_hot_reload(
        interval=updated.skills_hot_reload_interval,
        debounce=updated.skills_hot_reload_debounce,
    )
    ai_client.agent_registry.start_hot_reload(
        interval=updated.skills_hot_reload_interval,
        debounce=updated.skills_hot_reload_debounce,
    )
    logger.info(
        "[配置] 技能热重载已更新: interval=%.2fs debounce=%.2fs",
        updated.skills_hot_reload_interval,
        updated.skills_hot_reload_debounce,
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
