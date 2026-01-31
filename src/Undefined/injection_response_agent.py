"""注入攻击回复生成器

用于根据 undefined 人设生成简短的嘲讽性回复
"""

import logging
import httpx
from typing import Any
from pathlib import Path
from datetime import datetime
import time
import asyncio

from Undefined.config import SecurityModelConfig
from Undefined.token_usage_storage import TokenUsageStorage, TokenUsage

logger = logging.getLogger(__name__)

# 加载系统提示词
PROMPT_PATH = Path("res/prompts/injection_response_agent.txt")
try:
    INJECTION_RESPONSE_SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
except Exception as e:
    logger.error(f"加载注入回复提示词失败: {e}")
    INJECTION_RESPONSE_SYSTEM_PROMPT = "你是一个充满敌意的、说话带刺的 AI 助手。"


class InjectionResponseAgent:
    """注入攻击回复生成器"""

    def __init__(self, security_config: SecurityModelConfig) -> None:
        """初始化回复生成器

        参数:
            security_config: 安全模型配置
        """
        self.security_config = security_config
        self._http_client = httpx.AsyncClient(timeout=120.0)
        self._token_usage_storage = TokenUsageStorage()

    async def generate_response(self, user_message: str) -> str:
        """生成嘲讽性回复

        参数:
            user_message: 用户的原始消息

        返回:
            生成的嘲讽性回复
        """
        start_time = time.perf_counter()
        try:
            # 构造请求
            request_body = self._build_request_body(
                messages=[
                    {"role": "system", "content": INJECTION_RESPONSE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"<user_message>{user_message}</user_message>",
                    },
                ],
                max_tokens=self.security_config.max_tokens,
            )

            response = await self._http_client.post(
                self.security_config.api_url,
                headers={
                    "Authorization": f"Bearer {self.security_config.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            response.raise_for_status()
            result = response.json()
            duration = time.perf_counter() - start_time

            # 记录 token 使用统计
            usage = result.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", 0)

            logger.info(
                f"[注入回复] 生成完成, 耗时={duration:.2f}s, "
                f"Tokens={total_tokens} (P:{prompt_tokens} + C:{completion_tokens}), "
                f"模型={self.security_config.model_name}"
            )

            # 异步记录 token 使用
            asyncio.create_task(
                self._token_usage_storage.record(
                    TokenUsage(
                        timestamp=datetime.now().isoformat(),
                        model_name=self.security_config.model_name,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        duration_seconds=duration,
                        call_type="injection_response",
                        success=True,
                    )
                )
            )

            content = self._extract_choices_content(result).strip()

            # 去除所有换行符，确保 XML 格式正确
            content = content.replace("\n", " ").replace("\r", " ")
            # 去除多余空格
            content = " ".join(content.split())

            logger.debug(f"生成的嘲讽回复: {content}")

            return content if content else "无聊。"
        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.exception(f"生成嘲讽回复失败: {e}")
            # 失败时返回默认回复
            return "有病？"

    def _build_request_body(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> dict[str, Any]:
        """构建请求体"""
        body: dict[str, Any] = {
            "model": self.security_config.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.7,  # 稍微高一点的温度，让回复更有变化
        }

        # 添加 thinking 参数（如果启用）
        if self.security_config.thinking_enabled:
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.security_config.thinking_budget_tokens,
            }
        else:
            # 禁用 thinking
            body["thinking"] = {"enabled": False, "budget_tokens": 0}

        return body

    def _extract_choices_content(self, result: dict[str, Any]) -> str:
        """从 API 响应中提取 choices 的内容"""
        # 尝试从标准 OpenAI 格式提取
        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0]["message"]["content"]
            if isinstance(content, str):
                return content
            return str(content)

        # 尝试从 data.choices 提取
        if "data" in result and isinstance(result["data"], dict):
            data = result["data"]
            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0]["message"]["content"]
                if isinstance(content, str):
                    return content
                return str(content)

        # 如果都失败，抛出错误
        raise KeyError(f"无法从 API 响应中提取 choices 内容: {result}")

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        await self._http_client.aclose()
