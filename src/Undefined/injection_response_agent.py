"""注入攻击回复生成器

用于根据 undefined 人设生成简短的嘲讽性回复
"""

import logging
import time
from typing import Any

from Undefined.ai.llm import ModelRequester
from Undefined.ai.parsing import extract_choices_content
from Undefined.config import SecurityModelConfig
from Undefined.utils.resources import read_text_resource

logger = logging.getLogger(__name__)

_INJECTION_RESPONSE_SYSTEM_PROMPT: str | None = None


def _get_injection_response_prompt() -> str:
    global _INJECTION_RESPONSE_SYSTEM_PROMPT
    if _INJECTION_RESPONSE_SYSTEM_PROMPT is not None:
        return _INJECTION_RESPONSE_SYSTEM_PROMPT
    try:
        _INJECTION_RESPONSE_SYSTEM_PROMPT = read_text_resource(
            "res/prompts/injection_response_agent.txt"
        )
    except Exception as exc:
        logger.error("加载注入回复提示词失败: %s", exc)
        _INJECTION_RESPONSE_SYSTEM_PROMPT = "你是一个充满敌意的、说话带刺的 AI 助手。"
    return _INJECTION_RESPONSE_SYSTEM_PROMPT


class InjectionResponseAgent:
    """注入攻击回复生成器"""

    def __init__(
        self, security_config: SecurityModelConfig, requester: ModelRequester
    ) -> None:
        """初始化回复生成器

        参数:
            security_config: 安全模型配置
        """
        self.security_config = security_config
        self._requester = requester
        self._system_prompt = _get_injection_response_prompt()

    async def generate_response(self, user_message: str) -> str:
        """生成嘲讽性回复

        参数:
            user_message: 用户的原始消息

        返回:
            生成的嘲讽性回复
        """
        start_time = time.perf_counter()
        try:
            request_kwargs: dict[str, Any] = {"temperature": 0.7}
            if not self.security_config.thinking_enabled:
                request_kwargs["thinking"] = {"enabled": False, "budget_tokens": 0}

            result = await self._requester.request(
                model_config=self.security_config,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {
                        "role": "user",
                        "content": f"<user_message>{user_message}</user_message>",
                    },
                ],
                max_tokens=self.security_config.max_tokens,
                call_type="injection_response",
                **request_kwargs,
            )
            duration = time.perf_counter() - start_time

            logger.info(
                "[注入回复] 生成完成: elapsed=%.2fs model=%s",
                duration,
                self.security_config.model_name,
            )

            content = extract_choices_content(result).strip()

            # 去除所有换行符，确保 XML 格式正确
            content = content.replace("\n", " ").replace("\r", " ")
            # 去除多余空格
            content = " ".join(content.split())

            logger.debug("[注入回复] 生成内容: length=%s", len(content))

            return content if content else "无聊。"
        except Exception as exc:
            duration = time.perf_counter() - start_time
            logger.exception("[注入回复] 生成失败: %s elapsed=%.2fs", exc, duration)
            # 失败时返回默认回复
            return "有病？"

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        return None
