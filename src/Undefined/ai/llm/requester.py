"""统一 LLM 模型请求封装与请求体构建。

``ModelRequester`` 负责 OpenAI 兼容 API 的 chat/responses/embed/rerank 调用、
流式聚合与 token 用量记录；出站清洗与思维链提取委托 ``sanitize`` / ``thinking`` 子模块。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)

from Undefined.ai.llm.sanitize import (
    _tool_name_dot_delimiter,
    desc_preview,
    prepare_chat_completion_messages,
    relocate_system_to_first_user,
    sanitize_chat_completion_messages,
    sanitize_openai_messages_tool_arguments,
    sanitize_openai_tool_names_in_request,
    sanitize_openai_tools,
    tools_description_max_len,
    tools_description_truncate_enabled,
    tools_sanitize_verbose,
)
from Undefined.ai.llm.streaming import (
    aggregate_chat_completions_stream,
    aggregate_responses_stream,
    ensure_chat_stream_usage_options,
    should_fallback_from_stream,
    split_chat_completion_params,
    split_responses_params,
    without_stream_request_fields,
)
from Undefined.ai.llm.thinking import (
    extract_thinking_content,
    normalize_thinking_override,
)
from Undefined.ai.llm.types import ModelConfig
from Undefined.ai.parsing import extract_choices_content
from Undefined.ai.retrieval import RetrievalRequester
from Undefined.ai.tokens import TokenCounter
from Undefined.ai.transports import (
    API_MODE_CHAT_COMPLETIONS,
    API_MODE_RESPONSES,
    build_responses_request_body,
    get_api_mode,
    get_effort_payload,
    get_effort_style,
    get_thinking_payload,
    normalize_responses_result,
)
from Undefined.config import Config, EmbeddingModelConfig, RerankModelConfig, get_config
from Undefined.context import RequestContext
from Undefined.token_usage_storage import TokenUsage, TokenUsageStorage
from Undefined.utils.logging import log_debug_json, redact_string
from Undefined.utils.request_params import (
    merge_request_params,
    split_reserved_request_params,
)

logger = logging.getLogger(__name__)

__all__ = ["ModelRequester", "build_request_body", "ModelConfig"]

_SDK_REQUEST_OPTION_FIELDS: frozenset[str] = frozenset(
    {"extra_headers", "extra_query", "extra_body", "timeout"}
)

_CHAT_COMPLETIONS_RESERVED_FIELDS: frozenset[str] = (
    frozenset(
        {
            "model",
            "messages",
            "max_tokens",
            "tools",
            "tool_choice",
            "stream",
            "stream_options",
            "thinking",
            "reasoning",
            "reasoning_effort",
            "output_config",
        }
    )
    | _SDK_REQUEST_OPTION_FIELDS
)

_RESPONSES_RESERVED_FIELDS: frozenset[str] = (
    frozenset(
        {
            "model",
            "input",
            "instructions",
            "max_output_tokens",
            "tools",
            "tool_choice",
            "previous_response_id",
            "stream",
            "stream_options",
            "thinking",
            "reasoning",
            "reasoning_effort",
            "output_config",
        }
    )
    | _SDK_REQUEST_OPTION_FIELDS
)

_TOOLS_PARAM_INDEX_RE = re.compile(r"Tools\[(\d+)\]", re.IGNORECASE)
_RESPONSES_MISSING_TOOL_CALL_OUTPUT_RE = re.compile(
    r"no tool call found for function call output with call_id",
    re.IGNORECASE,
)

_PROMPT_CACHE_KEY_MAX_LEN = 128


def _get_runtime_config() -> Config | None:
    try:
        return get_config(strict=False)
    except Exception:
        return None


def _hash8(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]


def _normalize_prompt_cache_part(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "none"
    normalized_chars: list[str] = []
    for char in text:
        if char.isalnum() or char in {"-", "_", ":"}:
            normalized_chars.append(char)
        else:
            normalized_chars.append("_")
    normalized = "".join(normalized_chars).strip("_")
    return normalized or "none"


def _build_scope_prompt_cache_part() -> str:
    # prompt_cache_key 按会话 scope 隔离，避免群/私聊上下文串缓存
    ctx = RequestContext.current()
    if ctx is None:
        return "scope:global"
    if ctx.group_id is not None:
        return f"group:{_hash8(str(int(ctx.group_id)))}"
    if ctx.user_id is not None:
        return f"private:{_hash8(str(int(ctx.user_id)))}"
    if ctx.sender_id is not None:
        return f"sender:{_hash8(str(int(ctx.sender_id)))}"
    request_type = _normalize_prompt_cache_part(ctx.request_type)
    return f"type:{request_type}"


def _build_default_prompt_cache_key(model_config: ModelConfig, call_type: str) -> str:
    model_name = _normalize_prompt_cache_part(getattr(model_config, "model_name", ""))
    scope_part = _build_scope_prompt_cache_part()
    call_part = _normalize_prompt_cache_part(call_type)
    key = f"pc:{model_name}:{call_part}:{scope_part}"
    if len(key) <= _PROMPT_CACHE_KEY_MAX_LEN:
        return key
    suffix = "_" + _hash8(key)
    prefix_len = max(1, _PROMPT_CACHE_KEY_MAX_LEN - len(suffix))
    return key[:prefix_len] + suffix


def _responses_should_fallback_to_stateless_replay(
    exc: APIStatusError,
    request_body: dict[str, Any],
    *,
    stateless_replay: bool,
) -> bool:
    # 仅当续轮携带 function_call_output 且服务端报 call_id 不匹配时才降级
    if stateless_replay or not request_body.get("previous_response_id"):
        return False
    input_items = request_body.get("input")
    if not isinstance(input_items, list) or not any(
        isinstance(item, dict) and item.get("type") == "function_call_output"
        for item in input_items
    ):
        return False
    if exc.status_code != 400 or not isinstance(exc.body, dict):
        return False
    error = exc.body.get("error")
    if not isinstance(error, dict):
        return False
    message = str(error.get("message", "")).strip()
    param = str(error.get("param", "")).strip().lower()
    return param == "input" and bool(
        _RESPONSES_MISSING_TOOL_CALL_OUTPUT_RE.search(message)
    )


def _normalize_openai_base_url(
    api_url: str,
) -> tuple[str, dict[str, object] | None, bool]:
    """将旧式 /chat/completions URL 归一化为 OpenAI SDK 需要的 base_url。

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


def _warn_ignored_request_params(
    *,
    call_type: str,
    model_name: str,
    ignored: dict[str, Any],
) -> None:
    if not ignored:
        return
    logger.warning(
        "[request_params] ignored_keys=%s type=%s model=%s",
        ",".join(sorted(ignored)),
        call_type,
        model_name,
    )


def _build_effective_request_kwargs(
    model_config: ModelConfig,
    *,
    call_type: str,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    merged = merge_request_params(
        getattr(model_config, "request_params", {}),
        overrides,
    )
    thinking_override = overrides["thinking"] if "thinking" in overrides else None
    has_thinking_override = "thinking" in overrides
    reserved_fields = (
        _RESPONSES_RESERVED_FIELDS
        if get_api_mode(model_config) == API_MODE_RESPONSES
        else _CHAT_COMPLETIONS_RESERVED_FIELDS
    )
    allowed, ignored = split_reserved_request_params(
        merged,
        reserved_fields,
    )
    if has_thinking_override:
        ignored.pop("thinking", None)
    _warn_ignored_request_params(
        call_type=call_type,
        model_name=model_config.model_name,
        ignored=ignored,
    )
    if has_thinking_override:
        allowed["thinking"] = thinking_override
    return allowed


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
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._retrieval_requester = RetrievalRequester(
            get_openai_client=self._get_openai_client_for_model,
            response_to_dict=self._response_to_dict,
            get_token_counter=self._get_token_counter,
            record_usage=self._record_usage,
        )

    async def request(
        self,
        model_config: ModelConfig,
        messages: list[dict[str, Any]],
        max_tokens: int = 8192,
        call_type: str = "chat",
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        transport_state: dict[str, Any] | None = None,
        message_count_for_transport: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """发送请求到模型 API。"""
        start_time = time.perf_counter()
        cot_compat = getattr(model_config, "thinking_tool_call_compat", False)
        reasoning_replay = bool(
            getattr(model_config, "reasoning_content_replay", False)
        )
        api_mode = get_api_mode(model_config)
        transport_message_count = (
            message_count_for_transport
            if message_count_for_transport is not None
            else len(messages)
        )
        messages_for_api, tool_args_fixed = sanitize_openai_messages_tool_arguments(
            messages
        )
        if tool_args_fixed and logger.isEnabledFor(logging.INFO):
            logger.info(
                "[messages.sanitize] tool_args_fixed=%s messages=%s",
                tool_args_fixed,
                len(messages_for_api),
            )
        if api_mode == API_MODE_CHAT_COMPLETIONS:
            (
                messages_for_api,
                stripped_message_count,
                stripped_message_fields,
            ) = sanitize_chat_completion_messages(
                messages_for_api,
                preserve_reasoning_content=reasoning_replay,
            )
            if bool(getattr(model_config, "system_prompt_as_user", False)):
                messages_for_api = relocate_system_to_first_user(messages_for_api)
            if stripped_message_count and logger.isEnabledFor(logging.INFO):
                details = ",".join(
                    f"{key}={value}"
                    for key, value in sorted(stripped_message_fields.items())
                )
                logger.info(
                    "[chat_completions.standardize] stripped_internal_message_fields=%s messages=%s",
                    details,
                    stripped_message_count,
                )

        tools_for_api = tools
        api_to_internal: dict[str, str] = {}
        internal_to_api: dict[str, str] = {}
        if isinstance(tools_for_api, list):
            request_for_sanitize = {
                "messages": messages_for_api,
                "tools": list(tools_for_api),
            }
            api_to_internal, internal_to_api = sanitize_openai_tool_names_in_request(
                request_for_sanitize
            )
            raw_messages = request_for_sanitize.get("messages")
            if isinstance(raw_messages, list):
                messages_for_api = raw_messages
            raw_tools = request_for_sanitize.get("tools")
            if isinstance(raw_tools, list):
                tools_for_api = raw_tools

        if isinstance(tools_for_api, list):
            sanitized_tools, changed_count, changes = sanitize_openai_tools(
                tools_for_api
            )
            tools_for_api = sanitized_tools
            if changed_count and logger.isEnabledFor(logging.INFO):
                logger.info(
                    "[tools.sanitize] changed=%s total=%s truncate_enabled=%s max_desc_len=%s",
                    changed_count,
                    len(sanitized_tools),
                    tools_description_truncate_enabled(),
                    tools_description_max_len(),
                )
                if tools_sanitize_verbose():
                    for change in changes:
                        logger.info(
                            "[tools.sanitize.item] index=%s name=%s reasons=%s old_len=%s new_len=%s old=%s new=%s",
                            change.get("index"),
                            change.get("name"),
                            ",".join(change.get("reasons", [])),
                            change.get("old_len"),
                            change.get("new_len"),
                            change.get("old_preview"),
                            change.get("new_preview"),
                        )

        effective_kwargs = _build_effective_request_kwargs(
            model_config,
            call_type=call_type,
            overrides=dict(kwargs),
        )
        if bool(
            getattr(model_config, "prompt_cache_enabled", True)
        ) and not effective_kwargs.get("prompt_cache_key"):
            effective_kwargs["prompt_cache_key"] = _build_default_prompt_cache_key(
                model_config,
                call_type,
            )
        responses_stateless_replay = bool(
            getattr(model_config, "responses_force_stateless_replay", False)
        ) or bool(
            isinstance(transport_state, dict)
            and transport_state.get("stateless_replay")
        )
        effective_transport_state: dict[str, Any] | None
        if responses_stateless_replay:
            effective_transport_state = dict(transport_state or {})
            effective_transport_state["stateless_replay"] = True
        else:
            effective_transport_state = transport_state
        request_body = build_request_body(
            model_config=model_config,
            messages=messages_for_api,
            max_tokens=max_tokens,
            tools=tools_for_api,
            tool_choice=tool_choice,
            internal_to_api=internal_to_api,
            transport_state=effective_transport_state,
            **effective_kwargs,
        )

        try:
            if cot_compat and logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "[思维链兼容] enabled=%s type=%s model=%s api_mode=%s thinking_enabled=%s tools=%s messages=%s",
                    cot_compat,
                    call_type,
                    model_config.model_name,
                    api_mode,
                    getattr(model_config, "thinking_enabled", False),
                    bool(tools),
                    len(messages),
                )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "[API请求] type=%s model=%s api_mode=%s url=%s max_tokens=%s tools=%s tool_choice=%s messages=%s",
                    call_type,
                    model_config.model_name,
                    api_mode,
                    model_config.api_url,
                    max_tokens,
                    bool(tools_for_api),
                    tool_choice,
                    len(messages),
                )
                log_debug_json(logger, "[API请求体]", request_body)

            try:
                raw_result = await self._request_with_openai(
                    model_config,
                    request_body,
                )
            except APIStatusError as exc:
                # Responses 续轮失败：自动切换 stateless replay 重发全量 input
                if (
                    api_mode == API_MODE_RESPONSES
                    and _responses_should_fallback_to_stateless_replay(
                        exc,
                        request_body,
                        stateless_replay=responses_stateless_replay,
                    )
                ):
                    logger.warning(
                        "[responses.compat] previous_response_id 续轮失败，自动降级为 stateless replay: model=%s call_type=%s previous_response_id=%s",
                        model_config.model_name,
                        call_type,
                        request_body.get("previous_response_id", ""),
                    )
                    effective_transport_state = dict(effective_transport_state or {})
                    effective_transport_state["stateless_replay"] = True
                    responses_stateless_replay = True
                    request_body = build_request_body(
                        model_config=model_config,
                        messages=messages_for_api,
                        max_tokens=max_tokens,
                        tools=tools_for_api,
                        tool_choice=tool_choice,
                        internal_to_api=internal_to_api,
                        transport_state=effective_transport_state,
                        **effective_kwargs,
                    )
                    if logger.isEnabledFor(logging.DEBUG):
                        log_debug_json(
                            logger, "[API请求体][stateless replay]", request_body
                        )
                    raw_result = await self._request_with_openai(
                        model_config,
                        request_body,
                    )
                else:
                    raise
            if api_mode == API_MODE_RESPONSES:
                result = normalize_responses_result(
                    raw_result,
                    api_to_internal if api_to_internal else None,
                )
                response_id = str(
                    raw_result.get("id") or result.get("id") or ""
                ).strip()
                if response_id:
                    choice = result.get("choices", [{}])[0]
                    message = (
                        choice.get("message", {}) if isinstance(choice, dict) else {}
                    )
                    tool_calls = (
                        message.get("tool_calls", [])
                        if isinstance(message, dict)
                        else []
                    )
                    # 记录续轮锚点：下一轮只发送 tool_result 及之后的消息
                    result["_transport_state"] = {
                        "api_mode": api_mode,
                        "previous_response_id": response_id,
                        "tool_result_start_index": transport_message_count
                        + (1 if tool_calls else 0),
                    }
                    if responses_stateless_replay:
                        result["_transport_state"]["stateless_replay"] = True
            else:
                result = self._normalize_result(raw_result)
            if api_to_internal:
                result["_tool_name_map"] = {
                    "api_to_internal": api_to_internal,
                    "internal_to_api": internal_to_api,
                    "dot_delimiter": _tool_name_dot_delimiter(),
                }
            duration = time.perf_counter() - start_time

            usage = result.get("usage", {}) or {}
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            total_tokens = int(usage.get("total_tokens", 0) or 0)
            if total_tokens == 0 and (prompt_tokens or completion_tokens):
                total_tokens = prompt_tokens + completion_tokens
            if total_tokens == 0:
                prompt_tokens, completion_tokens, total_tokens = self._estimate_usage(
                    model_config.model_name, messages_for_api, result
                )

            logger.info(
                f"[API响应] {call_type} 完成: 耗时={duration:.2f}s, "
                f"Tokens={total_tokens} (P:{prompt_tokens} + C:{completion_tokens}), "
                f"模型={model_config.model_name}"
            )

            if logger.isEnabledFor(logging.DEBUG):
                log_debug_json(logger, "[API响应体]", result)

            self._maybe_log_thinking(result, call_type, model_config.model_name)

            self._record_usage(
                model_name=model_config.model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                duration_seconds=duration,
                call_type=call_type,
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
            if (
                exc.status_code == 400
                and isinstance(exc.body, dict)
                and isinstance(exc.body.get("error"), dict)
            ):
                param = exc.body.get("error", {}).get("param")
                if isinstance(param, str):
                    match = _TOOLS_PARAM_INDEX_RE.search(param)
                    if match and isinstance(request_body.get("tools"), list):
                        try:
                            idx = int(match.group(1))
                        except ValueError:
                            idx = -1
                        if 0 <= idx < len(request_body["tools"]):
                            tool = request_body["tools"][idx]
                            tool_name = (
                                tool.get("function", {}).get("name")
                                if isinstance(tool, dict)
                                else ""
                            )
                            desc_len: int | None = None
                            desc_preview_text = ""
                            if isinstance(tool, dict):
                                function = tool.get("function", {})
                                if isinstance(function, dict):
                                    desc = function.get("description")
                                    if desc is not None:
                                        desc_str = (
                                            desc if isinstance(desc, str) else str(desc)
                                        )
                                        desc_len = len(desc_str)
                                        desc_preview_text = desc_preview(desc_str)
                            logger.error(
                                "[tools.invalid] index=%s name=%s desc_len=%s desc=%s param=%s",
                                idx,
                                tool_name,
                                desc_len,
                                desc_preview_text,
                                param,
                            )
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
        runtime_config = _get_runtime_config()
        if runtime_config is None:
            return True
        return bool(runtime_config.log_thinking)

    def _maybe_log_thinking(
        self, result: dict[str, Any], call_type: str, model_name: str
    ) -> None:
        if not self._thinking_logging_enabled():
            return
        thinking = extract_thinking_content(result)
        if thinking:
            logger.info(
                "[思维链] type=%s model=%s content=%s",
                call_type,
                model_name,
                redact_string(thinking),
            )

    async def _request_with_openai(
        self,
        model_config: ModelConfig,
        request_body: dict[str, Any],
    ) -> dict[str, Any]:
        client = self._get_openai_client_for_model(model_config)
        if bool(getattr(model_config, "stream_enabled", False)):
            try:
                return await self._request_with_openai_streaming(
                    # client, model_config, request_body
                    client,
                    model_config,
                    request_body,
                )
            except Exception as exc:
                # 上游不支持流式时，剥离 stream 字段后降级为非流式重试
                if not should_fallback_from_stream(exc):
                    raise
                logger.warning(
                    "[API流式回退] model=%s api_mode=%s reason=%s",
                    getattr(model_config, "model_name", ""),
                    get_api_mode(model_config),
                    type(exc).__name__,
                )
                request_body = without_stream_request_fields(request_body)
        if get_api_mode(model_config) == API_MODE_RESPONSES:
            params, extra_body = split_responses_params(request_body)
            if extra_body:
                params["extra_body"] = extra_body
            response = await client.responses.create(**params)
            return self._response_to_dict(response)
        params, extra_body = split_chat_completion_params(request_body)
        if extra_body:
            params["extra_body"] = extra_body
        response = await client.chat.completions.create(**params)
        return self._response_to_dict(response)

    async def _request_with_openai_streaming(
        self,
        client: AsyncOpenAI,
        model_config: ModelConfig,
        request_body: dict[str, Any],
    ) -> dict[str, Any]:
        api_mode = get_api_mode(model_config)
        stream_body = dict(request_body)
        stream_body["stream"] = True
        if api_mode == API_MODE_RESPONSES:
            return await self._stream_responses_request(
                client,
                stream_body,
            )
        ensure_chat_stream_usage_options(stream_body)
        return await self._stream_chat_completions_request(
            # client, stream_body, model_config
            client,
            stream_body,
            model_config,
        )

    async def _stream_chat_completions_request(
        self,
        client: AsyncOpenAI,
        request_body: dict[str, Any],
        model_config: ModelConfig,
    ) -> dict[str, Any]:
        params, extra_body = split_chat_completion_params(request_body)
        if extra_body:
            params["extra_body"] = extra_body
        response = await client.chat.completions.create(**params)

        reasoning_replay = bool(
            getattr(model_config, "reasoning_content_replay", False)
        )
        chunks: list[dict[str, Any]] = []
        async for chunk in response:
            chunk_dict = self._response_to_dict(chunk)
            chunks.append(chunk_dict)
        return aggregate_chat_completions_stream(
            chunks,
            reasoning_replay=reasoning_replay,
        )

    async def _stream_responses_request(
        self,
        client: AsyncOpenAI,
        request_body: dict[str, Any],
    ) -> dict[str, Any]:
        params, extra_body = split_responses_params(request_body)
        if extra_body:
            params["extra_body"] = extra_body
        stream = await client.responses.create(**params)

        events: list[dict[str, Any]] = []
        async for event in stream:
            event_dict = self._response_to_dict(event)
            events.append(event_dict)
        return aggregate_responses_stream(events)

    async def embed(
        self,
        model_config: EmbeddingModelConfig,
        texts: list[str],
    ) -> list[list[float]]:
        """调用统一检索请求层的 embeddings。"""
        return await self._retrieval_requester.embed(model_config, texts)

    async def rerank(
        self,
        model_config: RerankModelConfig,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """调用统一检索请求层的 rerank。"""
        return await self._retrieval_requester.rerank(
            model_config=model_config,
            query=query,
            documents=documents,
            top_n=top_n,
        )

    def _get_openai_client_for_model(self, model_config: ModelConfig) -> AsyncOpenAI:
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
        return self._get_openai_client(
            base_url=base_url,
            api_key=model_config.api_key,
            default_query=default_query,
        )

    def _record_usage(
        self,
        *,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        duration_seconds: float,
        call_type: str,
    ) -> None:
        task = asyncio.create_task(
            self._token_usage_storage.record(
                TokenUsage(
                    timestamp=datetime.now().isoformat(),
                    model_name=model_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    duration_seconds=duration_seconds,
                    call_type=call_type,
                    success=True,
                )
            )
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

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
            timeout=480.0,
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
                raw_json = to_json()
                loaded = json.loads(str(raw_json))
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
                    # 无 tool_calls 与有 tool_calls 走不同分支
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
    internal_to_api: dict[str, str] | None = None,
    transport_state: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """构建 API 请求体。"""
    api_mode = get_api_mode(model_config)
    extra_kwargs: dict[str, Any] = dict(kwargs)

    if "thinking" in extra_kwargs:
        normalized = normalize_thinking_override(
            extra_kwargs.get("thinking"), model_config
        )
        if normalized is None:
            extra_kwargs.pop("thinking", None)
        else:
            extra_kwargs["thinking"] = normalized

    if api_mode == API_MODE_RESPONSES:
        extra_kwargs.pop("reasoning", None)
        extra_kwargs.pop("reasoning_effort", None)
        extra_kwargs.pop("output_config", None)
        return build_responses_request_body(
            model_config,
            messages,
            max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            extra_kwargs=extra_kwargs,
            internal_to_api=internal_to_api or {},
            transport_state=transport_state,
        )

    body: dict[str, Any] = {
        "model": model_config.model_name,
        "messages": prepare_chat_completion_messages(model_config, messages),
        "max_tokens": max_tokens,
    }

    extra_kwargs.pop("reasoning", None)
    extra_kwargs.pop("reasoning_effort", None)
    extra_kwargs.pop("output_config", None)

    thinking = get_thinking_payload(model_config)
    if thinking is not None:
        body["thinking"] = thinking

    effort_payload = get_effort_payload(model_config)
    if effort_payload is not None:
        style = get_effort_style(model_config)
        # Anthropic 风格走 output_config，OpenAI 风格走 reasoning_effort
        if style == "anthropic":
            body["output_config"] = effort_payload
        else:
            body["reasoning_effort"] = effort_payload["effort"]

    if tools:
        body["tools"] = tools
        thinking_active = "thinking" in body
        # 部分 thinking 模型不接受 dict 形 tool_choice，强制降为 auto
        if thinking_active and isinstance(tool_choice, dict):
            body["tool_choice"] = "auto"
        else:
            body["tool_choice"] = tool_choice

    body.update(extra_kwargs)
    return body
