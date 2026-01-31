"""HTTP model request handling."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

import httpx

from Undefined.config import ChatModelConfig, VisionModelConfig, AgentModelConfig
from Undefined.token_usage_storage import TokenUsageStorage, TokenUsage
from Undefined.utils.logging import log_debug_json, redact_string

logger = logging.getLogger(__name__)

ModelConfig = ChatModelConfig | VisionModelConfig | AgentModelConfig


class ModelRequester:
    """统一的模型请求封装。"""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        token_usage_storage: TokenUsageStorage,
    ) -> None:
        self._http_client = http_client
        self._token_usage_storage = token_usage_storage

    async def request(
        self,
        model_config: ModelConfig,
        messages: list[dict[str, Any]],
        max_tokens: int = 8192,
        call_type: str = "chat",
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """发送请求到模型 API。"""
        start_time = time.perf_counter()
        request_body = build_request_body(
            model_config=model_config,
            messages=messages,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )

        try:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "[API请求] type=%s model=%s url=%s max_tokens=%s tools=%s tool_choice=%s messages=%s",
                    call_type,
                    model_config.model_name,
                    model_config.api_url,
                    max_tokens,
                    bool(tools),
                    tool_choice,
                    len(messages),
                )
                log_debug_json(logger, "[API请求体]", request_body)

            response = await self._http_client.post(
                model_config.api_url,
                headers={
                    "Authorization": f"Bearer {model_config.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            duration = time.perf_counter() - start_time

            usage = result.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", 0)

            logger.info(
                f"[API响应] {call_type} 完成: 耗时={duration:.2f}s, "
                f"Tokens={total_tokens} (P:{prompt_tokens} + C:{completion_tokens}), "
                f"模型={model_config.model_name}"
            )

            if logger.isEnabledFor(logging.DEBUG):
                request_id = response.headers.get(
                    "x-request-id"
                ) or response.headers.get("request-id", "")
                logger.debug(
                    "[API响应] status=%s request_id=%s content_type=%s",
                    response.status_code,
                    request_id,
                    response.headers.get("content-type", ""),
                )
                log_debug_json(logger, "[API响应体]", result)

            asyncio.create_task(
                self._token_usage_storage.record(
                    TokenUsage(
                        timestamp=datetime.now().isoformat(),
                        model_name=model_config.model_name,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        duration_seconds=duration,
                        call_type=call_type,
                        success=True,
                    )
                )
            )

            return result
        except httpx.HTTPStatusError as exc:
            response = exc.response
            logger.error(
                "[API响应错误] status=%s url=%s body=%s",
                response.status_code,
                response.request.url,
                redact_string(response.text),
            )
            if logger.isEnabledFor(logging.DEBUG):
                try:
                    log_debug_json(logger, "[API错误响应体]", response.json())
                except ValueError:
                    pass
            raise
        except Exception as exc:
            logger.exception(f"[model.request.error] {call_type} 调用失败: {exc}")
            raise


def build_request_body(
    model_config: ModelConfig,
    messages: list[dict[str, Any]],
    max_tokens: int,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str = "auto",
    **kwargs: Any,
) -> dict[str, Any]:
    """构建 API 请求体。"""
    body: dict[str, Any] = {
        "model": model_config.model_name,
        "messages": messages,
        "max_tokens": max_tokens,
    }

    if model_config.thinking_enabled:
        body["thinking"] = {
            "type": "enabled",
            "budget_tokens": model_config.thinking_budget_tokens,
        }

    if tools:
        body["tools"] = tools
        body["tool_choice"] = tool_choice

    body.update(kwargs)
    return body
