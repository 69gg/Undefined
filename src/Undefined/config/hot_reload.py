from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
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
    # 嵌入/重排运行时在启动时构造，热更新仅提示需要重启
    "embedding_model",
    "embedding_features",
    "rerank_model",
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
    "lxmusic2api_base_url",
    "lxmusic2api_api_key",
    "prompt_file_includes",
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

# 安全服务持有的是同一个 Config 实例（原地更新即可见），只有注入回复 Agent
# 依赖的模型配置与重试次数变化时才需要重建该步骤
_SECURITY_KEYS: set[str] = {
    "security_model",
    "security_model_enabled",
    "ai_request_max_retries",
}

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


# 热更新创建的后台任务：持有强引用避免被 GC 回收，并统一回收异常
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def _spawn_hot_reload_task(
    coro: Coroutine[Any, Any, None],
    description: str,
) -> None:
    """创建热更新后台任务并回收异常，避免静默失败。"""
    task = asyncio.create_task(coro, name=f"config-hot-reload:{description}")
    _BACKGROUND_TASKS.add(task)

    def _on_done(finished: asyncio.Task[None]) -> None:
        _BACKGROUND_TASKS.discard(finished)
        if finished.cancelled():
            return
        exc = finished.exception()
        if exc is not None:
            logger.error(
                "[配置] 热更新后台任务失败: %s（该部分配置未生效）",
                description,
                exc_info=exc,
            )

    task.add_done_callback(_on_done)


def apply_config_updates(
    updated: Config,
    changes: dict[str, tuple[object, object]],
    context: HotReloadContext,
) -> None:
    """把热更新应用到运行时。

    每一步独立执行并捕获异常：单步失败不会中断其余步骤；失败项会以 error 级日志
    列出，避免出现“配置已改、行为未改”却无人知晓的隐蔽不一致。
    """
    if not changes:
        return

    changed_keys = set(changes.keys())
    logger.debug("[配置] 热更新变更项: %s", ", ".join(sorted(changed_keys)))
    _log_restart_required(changed_keys)

    handler = context.message_handler

    def _apply_security() -> None:
        context.security_service.apply_config(updated)

    def _apply_retries() -> None:
        context.queue_manager.update_max_retries(updated.ai_request_max_retries)

    def _apply_queue_intervals() -> None:
        context.queue_manager.update_model_intervals(
            build_model_queue_intervals(updated)
        )

    def _apply_intro() -> None:
        context.ai_client.apply_intro_config(
            AgentIntroGenConfig(
                enabled=updated.agent_intro_autogen_enabled,
                queue_interval_seconds=updated.agent_intro_autogen_queue_interval,
                max_tokens=updated.agent_intro_autogen_max_tokens,
                cache_path=Path(updated.agent_intro_hash_path),
            )
        )

    def _apply_search() -> None:
        context.ai_client.apply_search_config(updated.searxng_url)

    def _apply_attachments() -> None:
        context.ai_client.apply_attachment_config(updated)

    def _apply_message_batcher() -> None:
        if handler is None:
            logger.warning(
                "[配置] message_batcher 配置变更，但热更新上下文缺少 message_handler，"
                "本次变更未应用"
            )
            return
        if getattr(handler, "message_batcher", None) is None:
            logger.warning(
                "[配置] message_batcher 配置变更，但当前 message_handler 未装配 "
                "message_batcher，本次变更未应用"
            )
            return
        handler.message_batcher.update_config(updated.message_batcher)

    def _apply_automations() -> None:
        _spawn_hot_reload_task(
            _apply_message_handler_automations_hot_reload(updated, handler),
            "automations",
        )

    def _apply_model_configs() -> None:
        context.ai_client.apply_model_configs(
            chat_config=updated.chat_model,
            vision_config=updated.vision_model,
            agent_config=updated.agent_model,
            runtime_config=updated,
        )

    def _apply_runtime_config() -> None:
        context.ai_client.apply_runtime_config(updated)

    def _apply_skills_reload() -> None:
        _spawn_hot_reload_task(
            _apply_skills_hot_reload(updated, context.ai_client),
            "skills",
        )
        _spawn_hot_reload_task(
            _apply_message_handler_skills_hot_reload(updated, handler),
            "message-handler-skills",
        )

    def _apply_config_watcher() -> None:
        _spawn_hot_reload_task(
            _restart_config_hot_reload(
                context.config_manager,
                updated.skills_hot_reload_interval,
                updated.skills_hot_reload_debounce,
            ),
            "config-watcher",
        )

    steps: list[tuple[str, Callable[[], None]]] = []
    if _needs_security_update(changed_keys):
        steps.append(("security", _apply_security))
    if "ai_request_max_retries" in changed_keys:
        steps.append(("ai_request_max_retries", _apply_retries))
    if _needs_queue_interval_update(changed_keys):
        steps.append(("queue_intervals", _apply_queue_intervals))
    if _needs_intro_update(changed_keys):
        steps.append(("agent_intro", _apply_intro))
    if _needs_search_update(changed_keys):
        steps.append(("search", _apply_search))
    if _needs_attachment_update(changed_keys):
        steps.append(("attachments", _apply_attachments))
    if _needs_message_batcher_update(changed_keys):
        steps.append(("message_batcher", _apply_message_batcher))
    if _needs_automations_update(changed_keys):
        steps.append(("automations", _apply_automations))
    if _needs_core_ai_model_update(changed_keys):
        steps.append(("core_ai_models", _apply_model_configs))
    elif _needs_runtime_ai_model_update(changed_keys):
        steps.append(("runtime_ai_config", _apply_runtime_config))
    if _needs_skills_hot_reload_update(changed_keys):
        steps.append(("skills_hot_reload", _apply_skills_reload))
    if _needs_config_hot_reload_update(changed_keys):
        steps.append(("config_hot_reload", _apply_config_watcher))

    failed: list[str] = []
    for name, step in steps:
        try:
            step()
        except Exception:
            failed.append(name)
            logger.error("[配置] 热更新步骤失败: %s", name, exc_info=True)

    if failed:
        logger.error(
            "[配置] 热更新未完全生效（运行时状态与 config.toml 不一致）: %s；"
            "请修复配置或代码后重新保存配置，必要时重启进程。"
            "注意：技能热重载等异步步骤的失败不会出现在上面的列表，"
            "如怀疑异步部分未生效，请检索『热更新后台任务失败』日志",
            ", ".join(failed),
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


def _needs_security_update(changed_keys: set[str]) -> bool:
    if changed_keys & _SECURITY_KEYS:
        return True
    return any(key.startswith("security_model.") for key in changed_keys)


def _needs_attachment_update(changed_keys: set[str]) -> bool:
    return bool(changed_keys & _ATTACHMENT_KEYS)


def _needs_message_batcher_update(changed_keys: set[str]) -> bool:
    return any(
        key == "message_batcher" or key.startswith("message_batcher.")
        for key in changed_keys
    )


def _needs_automations_update(changed_keys: set[str]) -> bool:
    return any(
        key == "automations" or key.startswith("automations.") for key in changed_keys
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

    def _registry_name(registry: Any) -> str:
        return type(registry).__name__

    failed: list[str] = []
    if not updated.skills_hot_reload:
        for registry in registries:
            try:
                await registry.stop_hot_reload()
            except Exception:
                failed.append(_registry_name(registry))
                logger.error(
                    "[配置] 停止技能热重载失败: %s",
                    _registry_name(registry),
                    exc_info=True,
                )
        logger.info("[配置] 技能热重载已禁用")
        if failed:
            logger.error("[配置] 部分注册表热重载未停止: %s", ", ".join(failed))
        return

    for registry in registries:
        try:
            await registry.stop_hot_reload()
            registry.start_hot_reload(
                interval=updated.skills_hot_reload_interval,
                debounce=updated.skills_hot_reload_debounce,
            )
        except Exception:
            failed.append(_registry_name(registry))
            logger.error(
                "[配置] 重启技能热重载失败: %s", _registry_name(registry), exc_info=True
            )
    if failed:
        logger.error("[配置] 以下注册表热重载未生效: %s", ", ".join(failed))
        return
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


async def _apply_message_handler_automations_hot_reload(
    updated: Config,
    message_handler: MessageHandler | None,
) -> None:
    if message_handler is None:
        return
    await message_handler.apply_automations_hot_reload_config(
        max_concurrent=updated.automations.max_concurrent
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
