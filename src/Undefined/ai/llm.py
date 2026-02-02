"""LLM model request handling."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

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

__all__ = ["ModelRequester", "build_request_body", "ModelConfig"]

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


def _stringify_thinking_list(value: list[Any]) -> str:
    """将列表类型的思维链转换为字符串。

    Args:
        value: 思维链列表

    Returns:
        格式化后的字符串
    """
    parts = [_stringify_thinking(item) for item in value]
    return "\n".join([part for part in parts if part])


def _stringify_thinking_dict(value: dict[str, Any]) -> str:
    """将字典类型的思维链转换为字符串。

    Args:
        value: 思维链字典

    Returns:
        格式化后的字符串
    """
    content = value.get("content")
    if isinstance(content, str) and content:
        return content
    return str(value)


def _stringify_thinking(value: Any) -> str:
    """将思维链值转换为字符串。

    Args:
        value: 思维链值（可以是 None、字符串、列表或字典）

    Returns:
        格式化后的字符串
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return _stringify_thinking_list(value)
    if isinstance(value, dict):
        return _stringify_thinking_dict(value)
    return str(value)


def _extract_from_message(message: dict[str, Any]) -> str:
    """从 message 对象中提取思维链内容。

    Args:
        message: message 对象

    Returns:
        思维链内容字符串
    """
    if not isinstance(message, dict):
        return ""
    for key in _THINKING_KEYS:
        if key in message:
            return _stringify_thinking(message.get(key))
    return ""


def _extract_from_choice(choice: dict[str, Any]) -> str:
    """从 choice 对象中提取思维链内容。

    Args:
        choice: choice 对象

    Returns:
        思维链内容字符串
    """
    if not isinstance(choice, dict):
        return ""

    # 优先从 message 中提取
    message = choice.get("message")
    if isinstance(message, dict):
        thinking = _extract_from_message(message)
        if thinking:
            return thinking

    # 尝试从 choice 直接提取
    for key in _THINKING_KEYS:
        if key in choice:
            return _stringify_thinking(choice.get(key))

    return ""


def _extract_from_choices(choices: list[Any]) -> str:
    """从 choices 列表中提取思维链内容。

    Args:
        choices: choices 列表

    Returns:
        思维链内容字符串
    """
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0]
    return _extract_from_choice(choice)


def _extract_from_result(result: dict[str, Any]) -> str:
    """直接从结果对象中提取思维链内容。

    Args:
        result: API 响应结果

    Returns:
        思维链内容字符串
    """
    for key in _THINKING_KEYS:
        if key in result:
            return _stringify_thinking(result.get(key))
    return ""


def _extract_thinking_content(result: dict[str, Any]) -> str:
    """从 API 响应中提取思维链内容。

    提取优先级：
    1. 从 choices[0].message 中提取
    2. 从 choices[0] 直接提取
    3. 从响应根对象中提取

    Args:
        result: API 响应结果

    Returns:
        思维链内容字符串
    """
    # 尝试从 choices 中提取
    choices = result.get("choices")
    if isinstance(choices, list):
        thinking = _extract_from_choices(choices)
        if thinking:
            return thinking

    # 尝试从响应根对象中提取
    return _extract_from_result(result)


def _normalize_openai_base_url(
    api_url: str,
) -> tuple[str, dict[str, object] | None, bool]:
    """将 legacy 的 /chat/completions URL 归一化为 OpenAI SDK 需要的 base_url.

    兼容策略（B）：如果发现 api_url 末尾包含 /chat/completions，则自动裁剪为 base_url，
    以便统一走 OpenAI SDK，并给出弃用警告。
    """
    try:
        parts = urlsplit(api_url)
    except Exception:
        return api_url, None, False

    path = parts.path or ""
    trimmed_path = path.rstrip("/")
    suffix = "/chat/completions"
    if not trimmed_path.endswith(suffix):
        return api_url, None, False

    new_path = trimmed_path[: -len(suffix)]
    default_query: dict[str, object] | None = None
    if parts.query:
        default_query = {
            k: v for k, v in parse_qsl(parts.query, keep_blank_values=True)
        }
    normalized = urlunsplit(parts._replace(path=new_path, query="", fragment=""))
    return normalized, default_query, True


class ModelRequester:
    """统一的模型请求封装。"""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        token_usage_storage: TokenUsageStorage,
    ) -> None:
        self._http_client = http_client
        self._token_usage_storage = token_usage_storage
        self._openai_clients: dict[
            tuple[str, str, tuple[tuple[str, str], ...] | None], AsyncOpenAI
        ] = {}
        self._token_counters: dict[str, TokenCounter] = {}
        self._warned_legacy_api_urls: set[str] = set()

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
        ds_cot_enabled = getattr(model_config, "deepseek_new_cot_support", False)
        request_body = build_request_body(
            model_config=model_config,
            messages=messages,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )

        try:
            if ds_cot_enabled and logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "[DeepSeek CoT] enabled=%s type=%s model=%s thinking_enabled=%s tools=%s messages=%s",
                    ds_cot_enabled,
                    call_type,
                    model_config.model_name,
                    getattr(model_config, "thinking_enabled", False),
                    bool(tools),
                    len(messages),
                )

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

            result = await self._request_with_openai(model_config, request_body)
            result = self._normalize_result(result)
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
        except APIStatusError as exc:
            response = exc.response
            try:
                body = (
                    json.dumps(exc.body, ensure_ascii=False, default=str)
                    if exc.body is not None
                    else ""
                )
            except Exception:
                body = str(exc.body)
            logger.error(
                "[API响应错误] status=%s request_id=%s url=%s body=%s",
                exc.status_code,
                exc.request_id or "",
                response.request.url,
                redact_string(body),
            )
            raise
        except (APIConnectionError, APITimeoutError) as exc:
            logger.error("[API连接错误] type=%s message=%s", type(exc).__name__, exc)
            raise
        except Exception as exc:
            logger.exception(f"[model.request.error] {call_type} 调用失败: {exc}")
            raise

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

    async def _request_with_openai(
        self, model_config: ModelConfig, request_body: dict[str, Any]
    ) -> dict[str, Any]:
        base_url, default_query, changed = _normalize_openai_base_url(
            model_config.api_url
        )
        if changed and model_config.api_url not in self._warned_legacy_api_urls:
            self._warned_legacy_api_urls.add(model_config.api_url)
            logger.warning(
                "[配置弃用] 检测到 *_MODEL_API_URL 末尾包含 /chat/completions，这种写法已弃用；"
                "已自动裁剪为 base_url=%s（原值=%s）。",
                base_url,
                model_config.api_url,
            )

        client = self._get_openai_client(
            base_url=base_url, api_key=model_config.api_key, default_query=default_query
        )
        params, extra_body = _split_chat_completion_params(request_body)
        if extra_body:
            params["extra_body"] = extra_body
        response = await client.chat.completions.create(**params)
        return self._response_to_dict(response)

    def _get_openai_client(
        self, base_url: str, api_key: str, default_query: dict[str, object] | None
    ) -> AsyncOpenAI:
        query_key = None
        if default_query:
            query_key = tuple(
                sorted((str(k), str(v)) for k, v in default_query.items())
            )
        cache_key = (base_url, api_key, query_key)
        client = self._openai_clients.get(cache_key)
        if client is not None:
            return client
        # 复用上层注入的 httpx client（连接池/超时等），避免每个 OpenAI client 自建连接池。
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=120.0,
            default_query=default_query,
            http_client=self._http_client,
        )
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

    def _normalize_result(self, result: dict[str, Any]) -> dict[str, Any]:
        choices = result.get("choices")
        if isinstance(choices, list):
            return result
        data = result.get("data")
        if isinstance(data, dict):
            data_choices = data.get("choices")
            if isinstance(data_choices, list):
                normalized = dict(result)
                normalized["choices"] = data_choices
                return normalized
        normalized = dict(result)
        normalized["choices"] = [{}]
        return normalized

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
        if getattr(model_config, "deepseek_new_cot_support", False):
            # DeepSeek thinking mode 只需要 {"type":"enabled"}；额外字段可能导致兼容性问题。
            body["thinking"] = {"type": "enabled"}
        else:
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": model_config.thinking_budget_tokens,
            }

    if tools:
        body["tools"] = tools
        body["tool_choice"] = tool_choice

    body.update(kwargs)
    return body
