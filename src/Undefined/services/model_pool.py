"""多模型池私聊处理服务"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from Undefined.config.models import ChatModelConfig
from Undefined.utils.sender import MessageSender

if TYPE_CHECKING:
    from Undefined.config import Config

logger = logging.getLogger(__name__)


class ModelPoolService:
    """封装多模型池的私聊交互逻辑，与消息处理层解耦"""

    def __init__(self, ai: Any, config: "Config", sender: MessageSender) -> None:
        self._ai = ai
        self._config = config
        self._sender = sender

    async def handle_private_message(self, user_id: int, text: str) -> bool:
        """处理私聊多模型指令，返回 True 表示消息已被消费"""
        if not self._config.model_pool_enabled:
            return False

        selector = self._ai.model_selector

        selected = selector.try_resolve_compare(0, user_id, text)
        if selected:
            selector.set_preference(0, user_id, "chat", selected)
            await selector.save_preferences()
            await self._sender.send_private_message(
                user_id, f"已切换到模型: {selected}"
            )
            return True

        stripped = text.strip()
        for prefix in ("/compare ", "/pk "):
            if stripped.startswith(prefix):
                await self._run_compare(user_id, stripped[len(prefix) :].strip())
                return True

        return False

    async def _run_compare(self, user_id: int, prompt: str) -> None:
        if not prompt:
            await self._sender.send_private_message(user_id, "用法: /compare <问题>")
            return

        selector = self._ai.model_selector
        all_models = selector.get_all_chat_models(self._config.chat_model)

        if len(all_models) < 2:
            await self._sender.send_private_message(
                user_id, "模型池中只有一个模型，无法比较"
            )
            return

        await self._sender.send_private_message(
            user_id, f"正在向 {len(all_models)} 个模型发送问题，请稍候..."
        )

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

        async def _query(name: str, cfg: ChatModelConfig) -> tuple[str, str]:
            try:
                result = await self._ai.request_model(
                    model_config=cfg, messages=list(messages), call_type="compare"
                )
                content = (
                    result.get("choices", [{}])[0].get("message", {}).get("content", "")
                )
                return name, content.strip() or "(空回复)"
            except Exception as exc:
                return name, f"(请求失败: {exc})"

        results = await asyncio.gather(*[_query(n, c) for n, c in all_models])

        lines: list[str] = [f"问题: {prompt}", ""]
        for i, (name, content) in enumerate(results, 1):
            if len(content) > 500:
                content = content[:497] + "..."
            lines += [f"【{i}】{name}", content, ""]
        lines.append("回复「选X」可切换到该模型并继续对话")

        await self._sender.send_private_message(user_id, "\n".join(lines))
        selector.set_pending_compare(0, user_id, [n for n, _ in results])

    def select_chat_config(
        self, primary: ChatModelConfig, user_id: int
    ) -> ChatModelConfig:
        """按用户偏好/策略选择私聊 chat 模型"""
        result: ChatModelConfig = self._ai.model_selector.select_chat_config(
            primary,
            group_id=0,
            user_id=user_id,
            global_enabled=self._config.model_pool_enabled,
        )
        return result
