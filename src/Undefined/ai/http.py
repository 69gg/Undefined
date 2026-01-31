"""HTTP model request handling."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

import httpx
from openai import AsyncOpenAI

from Undefined.ai.parsing import extract_choices_content
from Undefined.ai.tokens import TokenCounter
from Undefined.config import (
    ChatModelConfig,
    VisionModelConfig,
    AgentModelConfig,
    SecurityModelConfig,
)
from Undefined.token_usage_storage import TokenUsageStorage, TokenUsage
from Undefined.utils.logging import log_debug_json, redact_string

logger = logging.getLogger(__name__)

ModelConfig = (
    ChatModelConfig | VisionModelConfig | AgentModelConfig | SecurityModelConfig
)

_CHAT_COMPLETIONS_KNOWN_FIELDS: set[str] = {
    "model",
    "messages",
    "max_tokens",
    "temperature",
    "top_p",
    "n",
    "stop",
    "presence_penalty",
    "frequency_penalty",
    "logit_bias",
    "user",
    "response_format",
    "seed",
    "stream",
    "stream_options",
    "tools",
    "tool_choice",
    "logprobs",
    "top_logprobs",
}

_THINKING_KEYS: tuple[str, ...] = (
    "thinking",
    "reasoning",
    "reasoning_content",
    "chain_of_thought",
    "cot",
    "thoughts",
)


def _split_chat_completion_params(
    body: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    known: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in body.items():
        if key in _CHAT_COMPLETIONS_KNOWN_FIELDS:
            known[key] = value
        else:
            extra[key] = value
    return known, extra


def _stringify_thinking(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_stringify_thinking(item) for item in value]
        return "\n".join([part for part in parts if part])
    if isinstance(value, dict):
        content = value.get("content")
        if isinstance(content, str) and content:
            return content
    return str(value)


def _extract_thinking_content(result: dict[str, Any]) -> str:
    choices = result.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            message = choice.get("message")
            if isinstance(message, dict):
                for key in _THINKING_KEYS:
                    if key in message:
                        return _stringify_thinking(message.get(key))
            for key in _THINKING_KEYS:
                if key in choice:
                    return _stringify_thinking(choice.get(key))
    for key in _THINKING_KEYS:
        if key in result:
            return _stringify_thinking(result.get(key))
    return ""


class ModelRequester:
    """统一的模型请求封装。"""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        token_usage_storage: TokenUsageStorage,
    ) -> None:
        self._http_client = http_client
        self._token_usage_storage = token_usage_storage
        self._openai_clients: dict[tuple[str, str], AsyncOpenAI] = {}
        self._token_counters: dict[str, TokenCounter] = {}

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

            response: httpx.Response | None = None
            if self._should_use_legacy_http(model_config.api_url):
                result, response = await self._request_with_httpx(
                    model_config, request_body
                )
            else:
                result = await self._request_with_openai(model_config, request_body)
            duration = time.perf_counter() - start_time

            usage = result.get("usage", {}) or {}
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            total_tokens = int(usage.get("total_tokens", 0) or 0)
            if total_tokens == 0 and (prompt_tokens or completion_tokens):
                total_tokens = prompt_tokens + completion_tokens
            if total_tokens == 0:
                prompt_tokens, completion_tokens, total_tokens = self._estimate_usage(
                    model_config.model_name, messages, result
                )

            logger.info(
                f"[API响应] {call_type} 完成: 耗时={duration:.2f}s, "
                f"Tokens={total_tokens} (P:{prompt_tokens} + C:{completion_tokens}), "
                f"模型={model_config.model_name}"
            )

            if logger.isEnabledFor(logging.DEBUG):
                if response is not None:
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

            self._maybe_log_thinking(result, call_type, model_config.model_name)

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

    def _should_use_legacy_http(self, api_url: str) -> bool:
        return "/chat/completions" in api_url

    def _thinking_logging_enabled(self) -> bool:
        value = os.getenv("LOG_THINKING", "true").strip().lower()
        return value not in {"0", "false", "no"}

    def _maybe_log_thinking(
        self, result: dict[str, Any], call_type: str, model_name: str
    ) -> None:
        if not self._thinking_logging_enabled():
            return
        thinking = _extract_thinking_content(result)
        if thinking:
            logger.info(
                "[思维链] type=%s model=%s content=%s",
                call_type,
                model_name,
                redact_string(thinking),
            )

    async def _request_with_httpx(
        self, model_config: ModelConfig, request_body: dict[str, Any]
    ) -> tuple[dict[str, Any], httpx.Response]:
        response = await self._http_client.post(
            model_config.api_url,
            headers={
                "Authorization": f"Bearer {model_config.api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
        response.raise_for_status()
        return response.json(), response

    async def _request_with_openai(
        self, model_config: ModelConfig, request_body: dict[str, Any]
    ) -> dict[str, Any]:
        client = self._get_openai_client(
            base_url=model_config.api_url, api_key=model_config.api_key
        )
        params, extra_body = _split_chat_completion_params(request_body)
        if extra_body:
            params["extra_body"] = extra_body
        response = await client.chat.completions.create(**params)
        return self._response_to_dict(response)

    def _get_openai_client(self, base_url: str, api_key: str) -> AsyncOpenAI:
        cache_key = (base_url, api_key)
        client = self._openai_clients.get(cache_key)
        if client is not None:
            return client
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
        self._openai_clients[cache_key] = client
        return client

    def _response_to_dict(self, response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        for attr in ("model_dump", "to_dict", "dict"):
            method = getattr(response, attr, None)
            if callable(method):
                try:
                    value = method()
                    if isinstance(value, dict):
                        return value
                except Exception:
                    continue
        to_json = getattr(response, "to_json", None)
        if callable(to_json):
            try:
                loaded = json.loads(to_json())
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass
        return {"data": str(response)}

    def _get_token_counter(self, model_name: str) -> TokenCounter:
        counter = self._token_counters.get(model_name)
        if counter is None:
            counter = TokenCounter(model_name)
            self._token_counters[model_name] = counter
        return counter

    def _estimate_usage(
        self,
        model_name: str,
        messages: list[dict[str, Any]],
        result: dict[str, Any],
    ) -> tuple[int, int, int]:
        counter = self._get_token_counter(model_name)
        try:
            prompt_text = "\n".join(
                json.dumps(message, ensure_ascii=False, default=str)
                for message in messages
            )
        except Exception:
            prompt_text = str(messages)
        prompt_tokens = counter.count(prompt_text)

        completion_text = ""
        try:
            completion_text = extract_choices_content(result)
        except Exception:
            completion_text = ""
        if not completion_text:
            choices = result.get("choices")
            if isinstance(choices, list) and choices:
                choice = choices[0]
                if isinstance(choice, dict):
                    message = choice.get("message", {})
                    tool_calls = (
                        message.get("tool_calls")
                        if isinstance(message, dict)
                        else choice.get("tool_calls")
                    )
                    if tool_calls:
                        try:
                            completion_text = json.dumps(
                                tool_calls, ensure_ascii=False, default=str
                            )
                        except Exception:
                            completion_text = str(tool_calls)
        completion_tokens = counter.count(completion_text) if completion_text else 0
        total_tokens = prompt_tokens + completion_tokens
        logger.debug(
            "[API响应] usage 缺失，估算 tokens: prompt=%s completion=%s total=%s",
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )
        return prompt_tokens, completion_tokens, total_tokens


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
