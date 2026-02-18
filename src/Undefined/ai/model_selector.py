"""模型池选择器"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from pathlib import Path

from Undefined.config.models import (
    AgentModelConfig,
    ChatModelConfig,
    ModelPool,
    ModelPoolEntry,
)
from Undefined.utils.io import read_json, write_json

logger = logging.getLogger(__name__)

_DEFAULT_PREFERENCES_PATH = Path("data/model_preferences.json")
_DEFAULT_COMPARE_EXPIRE_SECONDS = 300


class ModelSelector:
    """根据策略和用户偏好从模型池中选择模型"""

    def __init__(
        self,
        preferences_path: Path | None = None,
        compare_expire_seconds: float = _DEFAULT_COMPARE_EXPIRE_SECONDS,
    ) -> None:
        self._preferences_path = preferences_path or _DEFAULT_PREFERENCES_PATH
        self._compare_expire_seconds = compare_expire_seconds
        self._lock = asyncio.Lock()
        self._rr_counters: dict[str, int] = {}
        self._preferences: dict[tuple[int, int], dict[str, str]] = {}
        # pending_compares 只存模型名列表，不存配置对象
        self._pending_compares: dict[tuple[int, int], tuple[list[str], float]] = {}
        self._loaded = asyncio.Event()

    def select_chat_config(
        self,
        primary: ChatModelConfig,
        group_id: int = 0,
        user_id: int = 0,
        global_enabled: bool = True,
    ) -> ChatModelConfig:
        """选择 chat 模型配置"""
        if (
            not global_enabled
            or primary.pool is None
            or not primary.pool.enabled
            or not primary.pool.models
        ):
            return primary

        pref_key = (group_id, user_id)
        pref = self._preferences.get(pref_key, {}).get("chat")
        if pref:
            entry = self._find_entry(primary.pool, pref)
            if entry:
                return self._entry_to_chat_config(entry, primary)

        entry = self._select_by_strategy(primary.pool, "chat")
        if entry is None:
            return primary
        return self._entry_to_chat_config(entry, primary)

    def select_agent_config(
        self,
        primary: AgentModelConfig,
        group_id: int = 0,
        user_id: int = 0,
        global_enabled: bool = True,
    ) -> AgentModelConfig:
        """选择 agent 模型配置"""
        if (
            not global_enabled
            or primary.pool is None
            or not primary.pool.enabled
            or not primary.pool.models
        ):
            return primary

        pref_key = (group_id, user_id)
        pref = self._preferences.get(pref_key, {}).get("agent")
        if pref:
            entry = self._find_entry(primary.pool, pref)
            if entry:
                return self._entry_to_agent_config(entry, primary)

        entry = self._select_by_strategy(primary.pool, "agent")
        if entry is None:
            return primary
        return self._entry_to_agent_config(entry, primary)

    def get_all_chat_models(
        self, primary: ChatModelConfig
    ) -> list[tuple[str, ChatModelConfig]]:
        """获取所有可用 chat 模型（主模型 + 池中模型）"""
        result: list[tuple[str, ChatModelConfig]] = [(primary.model_name, primary)]
        if primary.pool and primary.pool.enabled:
            for entry in primary.pool.models:
                result.append(
                    (entry.model_name, self._entry_to_chat_config(entry, primary))
                )
        return result

    def set_preference(
        self, group_id: int, user_id: int, pool_key: str, model_name: str
    ) -> None:
        """设置用户模型偏好"""
        key = (group_id, user_id)
        if key not in self._preferences:
            self._preferences[key] = {}
        self._preferences[key][pool_key] = model_name

    def clear_preference(self, group_id: int, user_id: int, pool_key: str) -> None:
        """清除用户模型偏好"""
        key = (group_id, user_id)
        if key in self._preferences:
            self._preferences[key].pop(pool_key, None)

    def get_preference(self, group_id: int, user_id: int, pool_key: str) -> str | None:
        """获取用户模型偏好"""
        key = (group_id, user_id)
        return self._preferences.get(key, {}).get(pool_key)

    def set_pending_compare(
        self, group_id: int, user_id: int, model_names: list[str]
    ) -> None:
        """存储比较待选状态（只存模型名，不存配置对象）"""
        self._pending_compares[(group_id, user_id)] = (model_names, time.time())

    def try_resolve_compare(self, group_id: int, user_id: int, text: str) -> str | None:
        """尝试解析"选X"消息，返回选中的模型名"""
        key = (group_id, user_id)
        pending = self._pending_compares.get(key)
        if pending is None:
            return None
        model_names, ts = pending
        if time.time() - ts > self._compare_expire_seconds:
            self._pending_compares.pop(key, None)
            return None

        match = re.match(r"选\s*(\d+)", text.strip())
        if not match:
            return None
        idx = int(match.group(1))
        if idx < 1 or idx > len(model_names):
            return None

        self._pending_compares.pop(key, None)
        return model_names[idx - 1]

    async def load_preferences(self) -> None:
        """启动时从磁盘加载偏好"""
        async with self._lock:
            try:
                data = await read_json(self._preferences_path)
                if not isinstance(data, dict):
                    return
                for key_str, prefs in data.items():
                    parts = key_str.split("_", 1)
                    if len(parts) != 2:
                        continue
                    try:
                        gid, uid = int(parts[0]), int(parts[1])
                    except ValueError:
                        continue
                    if isinstance(prefs, dict):
                        self._preferences[(gid, uid)] = prefs
                logger.info("[模型选择器] 已加载 %d 个用户偏好", len(self._preferences))
            except FileNotFoundError:
                logger.debug("[模型选择器] 偏好文件不存在，跳过加载")
            except Exception as exc:
                logger.warning("[模型选择器] 加载偏好失败: %s", exc)
            finally:
                self._loaded.set()

    async def wait_ready(self) -> None:
        """等待偏好加载完成，供外部调用方确保初始化就绪"""
        await self._loaded.wait()

    async def save_preferences(self) -> None:
        """持久化偏好到磁盘"""
        async with self._lock:
            try:
                data: dict[str, dict[str, str]] = {}
                for (gid, uid), prefs in self._preferences.items():
                    if prefs:
                        data[f"{gid}_{uid}"] = prefs
                await write_json(self._preferences_path, data)
            except Exception as exc:
                logger.warning("[模型选择器] 保存偏好失败: %s", exc)

    def _select_by_strategy(
        self, pool: ModelPool, pool_key: str
    ) -> ModelPoolEntry | None:
        """按策略选择模型"""
        if pool.strategy == "default" or not pool.models:
            return None
        if pool.strategy == "random":
            return random.choice(pool.models)
        if pool.strategy == "round_robin":
            idx = self._rr_counters.get(pool_key, 0)
            entry = pool.models[idx % len(pool.models)]
            self._rr_counters[pool_key] = idx + 1
            return entry
        return None

    def _find_entry(self, pool: ModelPool, model_name: str) -> ModelPoolEntry | None:
        """在池中查找指定模型"""
        for entry in pool.models:
            if entry.model_name == model_name:
                return entry
        return None

    @staticmethod
    def _entry_to_chat_config(
        entry: ModelPoolEntry, primary: ChatModelConfig
    ) -> ChatModelConfig:
        """将 ModelPoolEntry 转为 ChatModelConfig"""
        return ChatModelConfig(
            api_url=entry.api_url,
            api_key=entry.api_key,
            model_name=entry.model_name,
            max_tokens=entry.max_tokens,
            queue_interval_seconds=entry.queue_interval_seconds,
            thinking_enabled=entry.thinking_enabled,
            thinking_budget_tokens=entry.thinking_budget_tokens,
            thinking_include_budget=entry.thinking_include_budget,
            thinking_tool_call_compat=entry.thinking_tool_call_compat,
            pool=primary.pool,
        )

    @staticmethod
    def _entry_to_agent_config(
        entry: ModelPoolEntry, primary: AgentModelConfig
    ) -> AgentModelConfig:
        """将 ModelPoolEntry 转为 AgentModelConfig"""
        return AgentModelConfig(
            api_url=entry.api_url,
            api_key=entry.api_key,
            model_name=entry.model_name,
            max_tokens=entry.max_tokens,
            queue_interval_seconds=entry.queue_interval_seconds,
            thinking_enabled=entry.thinking_enabled,
            thinking_budget_tokens=entry.thinking_budget_tokens,
            thinking_include_budget=entry.thinking_include_budget,
            thinking_tool_call_compat=entry.thinking_tool_call_compat,
            pool=primary.pool,
        )
