"""AI 客户端 ask 主循环与工具调用迭代。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from Undefined.ai.client.queue import ClientQueueMixin
from Undefined.ai.client.setup import (
    MISSING_TOOL_CALL_RETRY_HINT,
    SendMessageCallback,
    _build_invalid_tool_call_response,
)
from Undefined.ai.transports.openai_transport import RESPONSES_OUTPUT_ITEMS_KEY
from Undefined.ai.tooling import END_CO_CALL_REJECT_CONTENT
from Undefined.context import RequestContext
from Undefined.services.message_summary_fetch import fetch_session_messages
from Undefined.utils.logging import log_debug_json, redact_string
from Undefined.utils.tool_calls import parse_tool_arguments

logger = logging.getLogger(__name__)


def _webchat_agent_path(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _webchat_depth(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _webchat_call_id(parent_call_id: str, call_id: str, fallback: str) -> str:
    local_id = str(call_id or fallback or "tool").strip() or "tool"
    return f"{parent_call_id}/{local_id}" if parent_call_id else local_id


class ClientAskLoopMixin(ClientQueueMixin):
    """``ask()`` 多轮工具调用主循环。"""

    async def ask(
        self,
        question: str,
        context: str = "",
        send_message_callback: SendMessageCallback | None = None,
        get_recent_messages_callback: Callable[
            [str, str, int, int], Awaitable[list[dict[str, Any]]]
        ]
        | None = None,
        get_image_url_callback: Callable[[str], Awaitable[str | None]] | None = None,
        get_forward_msg_callback: Callable[[str], Awaitable[list[dict[str, Any]]]]
        | None = None,
        send_like_callback: Callable[[int, int], Awaitable[None]] | None = None,
        sender: Any = None,
        history_manager: Any = None,
        onebot_client: Any = None,
        scheduler: Any = None,
        extra_context: dict[str, Any] | None = None,
    ) -> str:
        """发送问题给 AI 并获取回复 (支持工具调用和迭代)

        参数:
            question: 用户输入的问题
            context: 额外的上下文背景
            send_message_callback: 发送消息的回调，支持可选的 reply_to
            get_recent_messages_callback: 获取上下文历史消息的回调
            get_image_url_callback: 获取图片 URL 的回调
            get_forward_msg_callback: 获取合并转发内容的回调
            send_like_callback: 点赞回调
            sender: 消息发送助手实例
            history_manager: 历史记录管理器实例
            onebot_client: OneBot 客户端实例
            scheduler: 任务调度器实例
            extra_context: 额外的上下文负载

        返回:
            AI 生成的最终文本回复
        """
        # ===== 阶段一：从 RequestContext / extra_context 组装 pre_context =====
        ctx = RequestContext.current()
        pre_context: dict[str, Any] = {}
        if ctx:
            if ctx.group_id is not None:
                pre_context["group_id"] = ctx.group_id
            if ctx.user_id is not None:
                pre_context["user_id"] = ctx.user_id
            if ctx.sender_id is not None:
                pre_context["sender_id"] = ctx.sender_id
            pre_context["request_type"] = ctx.request_type
            pre_context["request_id"] = ctx.request_id
        if extra_context:
            pre_context.update(extra_context)
        webchat_event_callback = pre_context.get("webchat_event_callback")
        if not callable(webchat_event_callback):
            webchat_event_callback = None

        async def emit_webchat_stage(stage: str, detail: Any | None = None) -> None:
            if webchat_event_callback is None:
                return
            payload: dict[str, Any] = {"stage": stage}
            if detail is not None:
                payload["detail"] = detail
            await webchat_event_callback("stage", payload)

        # ===== 阶段二：构建 LLM messages 与 OpenAI tools schema =====
        await emit_webchat_stage("building_context")
        messages = await self._prompt_builder.build_messages(
            question,
            get_recent_messages_callback=get_recent_messages_callback,
            extra_context=extra_context,
        )
        await emit_webchat_stage("context_ready")

        tools = self.tool_manager.get_openai_tools()
        tools = self._filter_tools_for_runtime_config(tools)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "[AI消息] 构建完成: messages=%s tools=%s question_len=%s",
                len(messages),
                len(tools),
                len(question),
            )
            log_debug_json(logger, "[AI消息内容]", messages)

        # ===== 阶段三：组装 tool_context，注入回调、服务与 RequestContext 字段 =====
        tool_context = ctx.get_resources() if ctx else {}
        tool_context["conversation_ended"] = False
        tool_context.setdefault("agent_histories", {})

        # 显式注入 RequestContext 的核心字段（与 tooling.py:execute_tool_call 保持一致）
        if ctx:
            if ctx.group_id is not None:
                tool_context.setdefault("group_id", ctx.group_id)
            if ctx.user_id is not None:
                tool_context.setdefault("user_id", ctx.user_id)
            if ctx.sender_id is not None:
                tool_context.setdefault("sender_id", ctx.sender_id)
            tool_context.setdefault("request_type", ctx.request_type)
            tool_context.setdefault("request_id", ctx.request_id)

        if extra_context:
            tool_context.update(extra_context)

        # 注入常用资源（用于工具执行）
        tool_context.setdefault("ai_client", self)
        tool_context.setdefault("runtime_config", self._get_runtime_config())
        tool_context.setdefault("search_wrapper", self._search_wrapper)
        tool_context.setdefault(
            "crawl4ai_available", self._crawl4ai_capabilities.available
        )
        tool_context.setdefault(
            "crawl4ai_proxy_config_available",
            self._crawl4ai_capabilities.proxy_config_available,
        )
        tool_context.setdefault("end_summary_storage", self._end_summary_storage)
        tool_context.setdefault("end_summaries", self._prompt_builder.end_summaries)
        tool_context.setdefault("webchat_parent_call_id", "")
        tool_context.setdefault("webchat_depth", 0)
        tool_context.setdefault("webchat_agent_path", [])
        tool_context.setdefault(
            "send_private_message_callback", self._send_private_message_callback
        )
        tool_context.setdefault("send_message_callback", send_message_callback)
        tool_context.setdefault(
            "get_recent_messages_callback", get_recent_messages_callback
        )

        async def fetch_session_messages_callback(
            *,
            group_id: int,
            user_id: int,
            count: int | None = None,
            time_range: str | None = None,
        ) -> str:
            return await fetch_session_messages(
                history_manager,
                group_id=group_id,
                user_id=user_id,
                count=count,
                time_range=time_range,
                runtime_config=self._get_runtime_config(),
            )

        tool_context.setdefault(
            "fetch_session_messages_callback", fetch_session_messages_callback
        )
        tool_context.setdefault("get_image_url_callback", get_image_url_callback)
        tool_context.setdefault("get_forward_msg_callback", get_forward_msg_callback)
        tool_context.setdefault("send_like_callback", send_like_callback)
        tool_context.setdefault("sender", sender)
        tool_context.setdefault("history_manager", history_manager)
        tool_context.setdefault("onebot_client", onebot_client)
        tool_context.setdefault("scheduler", scheduler)
        tool_context.setdefault("send_image_callback", self._send_image_callback)
        tool_context.setdefault(
            "attachment_registry",
            getattr(self, "attachment_registry", None),
        )
        tool_context.setdefault("memory_storage", self.memory_storage)
        tool_context.setdefault("knowledge_manager", self._knowledge_manager)
        tool_context.setdefault("cognitive_service", self._cognitive_service)
        tool_context.setdefault("meme_service", self._meme_service)
        tool_context.setdefault("current_question", question)
        message_ids = tool_context.get("message_ids")
        if not isinstance(message_ids, list):
            message_ids = []
            tool_context["message_ids"] = message_ids
        trigger_message_id = tool_context.get("trigger_message_id")
        if trigger_message_id is not None:
            trigger_message_id_text = str(trigger_message_id).strip()
            if trigger_message_id_text and trigger_message_id_text not in message_ids:
                message_ids.append(trigger_message_id_text)

        # ===== 阶段四：模型选择、思维链/重试参数与主循环状态初始化 =====
        await emit_webchat_stage("selecting_model")
        await self.model_selector.wait_ready()
        selected_model_name = pre_context.get("selected_model_name")
        if selected_model_name:
            effective_chat_config = self._find_chat_config_by_name(selected_model_name)
        else:
            effective_chat_config = self.chat_config

        max_iterations = 1000
        iteration = 0
        conversation_ended = False
        cot_compat = getattr(effective_chat_config, "thinking_tool_call_compat", False)
        capture_reasoning = cot_compat or bool(
            getattr(effective_chat_config, "reasoning_content_replay", False)
        )
        cot_compat_logged = False
        cot_missing_logged = False
        transport_state: dict[str, Any] | None = None
        queue_lane = self._resolve_queue_lane(tool_context.get("queue_lane"))
        pre_tool_failure_count = 0
        missing_tool_call_count = 0
        last_missing_tool_call_content = ""
        runtime_config = self._get_runtime_config()
        agent_registry = getattr(self, "agent_registry", None)
        get_agent_schemas = getattr(agent_registry, "get_agents_schema", None)
        raw_agent_schemas = get_agent_schemas() if callable(get_agent_schemas) else []
        agent_tool_names = {
            str(schema.get("function", {}).get("name") or "")
            for schema in raw_agent_schemas
            if isinstance(schema, dict)
        }
        max_pre_tool_retries = max(
            0,
            int(getattr(runtime_config, "ai_request_max_retries", 0) or 0),
        )
        max_missing_tool_call_retries = max(
            0,
            int(getattr(runtime_config, "missing_tool_call_retries", 3) or 0),
        )

        # ===== 阶段五：多轮 LLM + 工具调用主循环（每轮一次请求） =====
        while iteration < max_iterations:
            iteration += 1
            logger.info(f"[AI决策] 开始第 {iteration} 轮迭代...")
            message_checkpoint_len = len(messages)
            transport_state_checkpoint = transport_state

            tool_execution_started = False
            try:
                await emit_webchat_stage(
                    "waiting_model",
                    f"iteration={iteration} model={effective_chat_config.model_name}",
                )
                result = await self.submit_queued_llm_call(
                    model_config=effective_chat_config,
                    messages=messages,
                    max_tokens=8192,
                    call_type="chat",
                    tools=tools,
                    tool_choice="auto",
                    transport_state=transport_state,
                    queue_lane=queue_lane,
                )

                tool_name_map = (
                    result.get("_tool_name_map") if isinstance(result, dict) else None
                )
                api_to_internal: dict[str, str] = {}
                if isinstance(tool_name_map, dict):
                    raw_api_to_internal = tool_name_map.get("api_to_internal")
                    if isinstance(raw_api_to_internal, dict):
                        # LLM 出站时工具名可能被编码，执行前映射回内部名
                        api_to_internal = {
                            str(k): str(v) for k, v in raw_api_to_internal.items()
                        }

                next_transport_state = (
                    result.get("_transport_state") if isinstance(result, dict) else None
                )
                transport_state = (
                    next_transport_state
                    if isinstance(next_transport_state, dict)
                    else None
                )

                choice = result.get("choices", [{}])[0]
                message = choice.get("message", {})
                content: str = message.get("content") or ""
                reasoning_content = message.get("reasoning_content")
                tool_calls = message.get("tool_calls", [])
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "[AI响应] content_len=%s tool_calls=%s",
                        len(content),
                        len(tool_calls),
                    )
                    # 无 tool_calls 与有 tool_calls 走不同分支
                    if tool_calls:
                        log_debug_json(logger, "[AI工具调用]", tool_calls)

                log_thinking = self._get_runtime_config().log_thinking
                if (
                    capture_reasoning
                    and tools
                    and log_thinking
                    and not cot_compat_logged
                ):
                    cot_compat_logged = True
                    logger.info(
                        "[思维链兼容] 多轮工具调用 reasoning_content 本地回填已启用"
                    )
                if (
                    capture_reasoning
                    and log_thinking
                    and tools
                    and getattr(effective_chat_config, "thinking_enabled", False)
                    and not reasoning_content
                    and tool_calls
                    and not cot_missing_logged
                ):
                    cot_missing_logged = True
                    message_keys = (
                        ", ".join(sorted(message.keys()))
                        if isinstance(message, dict)
                        else type(message).__name__
                    )
                    logger.info(
                        "[思维链兼容] 未在响应中发现 reasoning_content（可能是模型/服务商不返回思维链）；message_keys=%s",
                        message_keys,
                    )

                # 部分模型会同时返回文本与 tool_calls；对外动作以工具为准，丢弃 content
                if content.strip() and tool_calls:
                    logger.debug(
                        "检测到 content 与工具调用同时存在，忽略 content，仅执行工具调用"
                    )
                    content = ""

                # 无 tool_calls 与有 tool_calls 走不同分支
                if not tool_calls:
                    if conversation_ended:
                        await emit_webchat_stage("finalizing")
                        logger.info(
                            "[AI回复] 会话结束，返回最终内容: length=%s",
                            len(content),
                        )
                        return content

                    # 未调用工具：累计重试次数，超限则 fallback 发送或直接返回文本
                    if content.strip():
                        last_missing_tool_call_content = content.strip()
                    missing_tool_call_count += 1
                    if missing_tool_call_count > max_missing_tool_call_retries:
                        logger.warning(
                            "[AI回复] 模型连续未调用工具，停止重试: iteration=%s retries=%s/%s content_len=%s",
                            iteration,
                            missing_tool_call_count - 1,
                            max_missing_tool_call_retries,
                            len(content),
                        )
                        fallback_content = last_missing_tool_call_content
                        if fallback_content and send_message_callback is not None:
                            try:
                                await emit_webchat_stage("sending_message")
                                await send_message_callback(fallback_content)
                                tool_context["message_sent_this_turn"] = True
                                current_ctx = RequestContext.current()
                                if current_ctx is not None:
                                    current_ctx.set_resource(
                                        "message_sent_this_turn", True
                                    )
                                return ""
                            except Exception:
                                logger.exception("[AI回复] fallback 发送失败")
                        return fallback_content

                    logger.warning(
                        "[AI回复] 模型返回文本但未调用工具（iteration=%s retry=%s/%s content_len=%s），要求重试",
                        iteration,
                        missing_tool_call_count,
                        max_missing_tool_call_retries,
                        len(content),
                    )
                    assistant_retry_message: dict[str, Any] = {
                        "role": "assistant",
                        "content": content,
                    }
                    if capture_reasoning and reasoning_content is not None:
                        assistant_retry_message["reasoning_content"] = reasoning_content
                    messages.append(assistant_retry_message)
                    messages.append(
                        {
                            "role": "user",
                            "content": MISSING_TOOL_CALL_RETRY_HINT,
                        }
                    )
                    continue

                await emit_webchat_stage("preparing_tools", len(tool_calls))
                assistant_message: dict[str, Any] = {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                }
                missing_tool_call_count = 0
                last_missing_tool_call_content = ""
                phase = message.get("phase")
                if phase is not None:
                    assistant_message["phase"] = phase
                output_items = message.get(RESPONSES_OUTPUT_ITEMS_KEY)
                if isinstance(output_items, list):
                    assistant_message[RESPONSES_OUTPUT_ITEMS_KEY] = output_items
                if capture_reasoning and reasoning_content is not None:
                    assistant_message["reasoning_content"] = reasoning_content
                messages.append(assistant_message)

                tool_tasks: list[asyncio.Task[Any]] = []
                tool_call_ids = []
                tool_api_names: list[str] = []
                tool_internal_names: list[str] = []
                end_tool_call: dict[str, Any] | None = None
                end_tool_args: dict[str, Any] = {}
                end_webchat_event_base: dict[str, Any] = {}
                tool_results: list[Any] = []

                # 逐个处理模型返回的 tool_call
                for tool_call in tool_calls:
                    call_id = ""
                    if isinstance(tool_call, dict):
                        call_id = str(tool_call.get("id", "") or "")
                        function = tool_call.get("function")
                    else:
                        function = None
                    if not isinstance(function, dict):
                        logger.warning(
                            "[工具调用] 跳过无效工具调用: missing_function ID=%s",
                            call_id,
                        )
                        messages.append(_build_invalid_tool_call_response(tool_call))
                        continue
                    api_function_name = str(function.get("name", "") or "").strip()
                    if not api_function_name:
                        logger.warning(
                            "[工具调用] 跳过无效工具调用: empty_name ID=%s",
                            call_id,
                        )
                        messages.append(_build_invalid_tool_call_response(tool_call))
                        continue
                    raw_args = function.get("arguments")

                    internal_function_name = api_to_internal.get(
                        api_function_name,
                        api_function_name,
                    )

                    if internal_function_name != api_function_name:
                        logger.info(
                            "[工具准备] 准备调用: %s (原名: %s) (ID=%s)",
                            internal_function_name,
                            api_function_name,
                            call_id,
                        )
                    else:
                        logger.info(
                            "[工具准备] 准备调用: %s (ID=%s)",
                            api_function_name,
                            call_id,
                        )
                    logger.debug(
                        f"[工具参数] {api_function_name} 参数: {redact_string(str(raw_args))}"
                    )

                    function_args = parse_tool_arguments(
                        raw_args,
                        logger=logger,
                        tool_name=str(api_function_name),
                    )

                    if not isinstance(function_args, dict):
                        function_args = {}
                    is_agent_call = internal_function_name in agent_tool_names
                    webchat_parent_call_id = str(
                        tool_context.get("webchat_parent_call_id") or ""
                    ).strip()
                    webchat_depth = _webchat_depth(tool_context.get("webchat_depth"))
                    webchat_agent_path = _webchat_agent_path(
                        tool_context.get("webchat_agent_path")
                    )
                    webchat_call_id = _webchat_call_id(
                        webchat_parent_call_id,
                        call_id,
                        internal_function_name,
                    )
                    webchat_event_base: dict[str, Any] = {
                        "webchat_call_id": webchat_call_id,
                        "parent_webchat_call_id": webchat_parent_call_id,
                        "depth": webchat_depth,
                        "agent_path": webchat_agent_path,
                    }
                    if webchat_event_callback is not None:
                        await webchat_event_callback(
                            "tool_start",
                            {
                                "tool_call_id": call_id,
                                "name": internal_function_name,
                                "api_name": api_function_name,
                                "arguments": function_args,
                                "is_agent": is_agent_call,
                                **webchat_event_base,
                            },
                        )

                    # 检测 end 工具，暂存后统一处理
                    if internal_function_name == "end":
                        # 无 tool_calls 与有 tool_calls 走不同分支
                        if len(tool_calls) > 1:
                            logger.warning(
                                "[工具调用] end 与其他工具同时调用，"
                                "将先执行其他工具，end 将返回拒绝结果"
                            )
                        end_tool_call = tool_call
                        end_tool_args = function_args
                        end_webchat_event_base = webchat_event_base
                        continue

                    tool_call_ids.append(call_id)
                    tool_api_names.append(str(api_function_name))
                    tool_internal_names.append(str(internal_function_name))
                    call_context = tool_context.copy()
                    if is_agent_call:
                        call_context["webchat_parent_call_id"] = webchat_call_id
                        call_context["webchat_depth"] = webchat_depth + 1
                        call_context["webchat_agent_path"] = [
                            *webchat_agent_path,
                            internal_function_name,
                        ]

                    async def _execute_tool_with_webchat_event(
                        *,
                        call_id: str,
                        api_name: str,
                        internal_name: str,
                        args: dict[str, Any],
                        context: dict[str, Any],
                        webchat_event_base: dict[str, Any],
                        is_agent_call: bool,
                    ) -> Any:
                        try:
                            result = await self.tool_manager.execute_tool(
                                internal_name, args, context
                            )
                        except Exception as exc:
                            if webchat_event_callback is not None:
                                await webchat_event_callback(
                                    "tool_end",
                                    {
                                        "tool_call_id": call_id,
                                        "name": internal_name,
                                        "api_name": api_name,
                                        "ok": False,
                                        "result": f"执行失败: {str(exc)}",
                                        "is_agent": is_agent_call,
                                        **webchat_event_base,
                                    },
                                )
                            raise
                        if webchat_event_callback is not None:
                            await webchat_event_callback(
                                "tool_end",
                                {
                                    "tool_call_id": call_id,
                                    "name": internal_name,
                                    "api_name": api_name,
                                    "ok": True,
                                    "result": str(result),
                                    "is_agent": is_agent_call,
                                    **webchat_event_base,
                                },
                            )
                        return result

                    tool_tasks.append(
                        asyncio.create_task(
                            _execute_tool_with_webchat_event(
                                call_id=call_id,
                                api_name=str(api_function_name),
                                internal_name=str(internal_function_name),
                                args=function_args,
                                context=call_context,
                                webchat_event_base=webchat_event_base,
                                is_agent_call=is_agent_call,
                            )
                        )
                    )

                if tool_tasks:
                    tool_execution_started = True
                    logger.info(
                        "[工具执行] 开始并发执行 %s 个工具调用: %s",
                        len(tool_tasks),
                        ", ".join(tool_internal_names),
                    )
                    await emit_webchat_stage(
                        "waiting_tools", ", ".join(tool_internal_names)
                    )
                    tool_results = await asyncio.gather(
                        *tool_tasks,
                        return_exceptions=True,
                    )

                    for i, tool_result in enumerate(tool_results):
                        call_id = tool_call_ids[i]
                        api_fname = tool_api_names[i]
                        internal_fname = tool_internal_names[i]

                        if isinstance(tool_result, Exception):
                            logger.error(
                                "[工具异常] %s (ID=%s) 执行抛出异常: %s",
                                internal_fname,
                                call_id,
                                tool_result,
                            )
                            content_str = f"执行失败: {str(tool_result)}"
                        else:
                            content_str = str(tool_result)
                            logger.debug(
                                "[工具响应] %s (ID=%s) 返回内容长度=%s",
                                internal_fname,
                                call_id,
                                len(content_str),
                            )
                            if logger.isEnabledFor(logging.DEBUG):
                                log_debug_json(
                                    logger,
                                    f"[工具响应体] {internal_fname} (ID={call_id})",
                                    content_str,
                                )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "name": api_fname,
                                "content": content_str,
                            }
                        )

                        # 如果是 get_forward_msg 工具调用，将其结果写入历史记录
                        if internal_fname == "get_forward_msg" and not isinstance(
                            tool_result, Exception
                        ):
                            task = asyncio.create_task(
                                self._save_forward_to_history(
                                    content_str,
                                    pre_context,
                                    history_manager,
                                )
                            )
                            task.add_done_callback(
                                lambda t: t.exception() if not t.cancelled() else None
                            )

                        # 会话是否已由 end 工具标记结束
                        if tool_context.get("conversation_ended"):
                            conversation_ended = True
                            logger.info(
                                "[会话状态] 工具触发会话结束标记: tool=%s",
                                internal_fname,
                            )

                if end_tool_call:
                    end_call_id = end_tool_call.get("id", "")
                    end_api_name = end_tool_call.get("function", {}).get("name", "end")
                    if tool_tasks:
                        if webchat_event_callback is not None:
                            await webchat_event_callback(
                                "tool_end",
                                {
                                    "tool_call_id": end_call_id,
                                    "name": "end",
                                    "api_name": end_api_name,
                                    "ok": False,
                                    "result": END_CO_CALL_REJECT_CONTENT,
                                    "is_agent": False,
                                    **end_webchat_event_base,
                                },
                            )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": end_call_id,
                                "name": end_api_name,
                                "content": END_CO_CALL_REJECT_CONTENT,
                            }
                        )
                        logger.info(
                            "[工具调用] end 与其他工具同时调用，"
                            "其它工具已执行，end 已回填拒绝响应"
                        )
                    else:
                        # end 单独调用，正常执行（参数已在循环中解析）
                        tool_execution_started = True
                        await emit_webchat_stage("waiting_tools", "end")
                        try:
                            end_result_raw = await self.tool_manager.execute_tool(
                                "end", end_tool_args, tool_context
                            )
                            end_result = str(end_result_raw)
                            end_ok = True
                        except Exception as exc:
                            logger.exception("[工具异常] end 执行抛出异常: %s", exc)
                            end_result = f"执行失败: {str(exc)}"
                            end_ok = False
                        if webchat_event_callback is not None:
                            await webchat_event_callback(
                                "tool_end",
                                {
                                    "tool_call_id": end_call_id,
                                    "name": "end",
                                    "api_name": end_api_name,
                                    "ok": end_ok,
                                    "result": end_result,
                                    "is_agent": False,
                                    **end_webchat_event_base,
                                },
                            )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": end_call_id,
                                "name": end_api_name,
                                "content": end_result,
                            }
                        )
                        # 会话是否已由 end 工具标记结束
                        if tool_context.get("conversation_ended"):
                            conversation_ended = True
                            logger.info("[会话状态] end 工具触发会话结束")

                # 会话是否已由 end 工具标记结束
                if conversation_ended:
                    await emit_webchat_stage("finalizing")
                    logger.info("[会话状态] 对话已结束（调用 end 工具）")
                    return ""
                pre_tool_failure_count = 0

            except Exception as exc:
                if (
                    not tool_execution_started
                    and pre_tool_failure_count < max_pre_tool_retries
                ):
                    pre_tool_failure_count += 1
                    del messages[message_checkpoint_len:]
                    transport_state = transport_state_checkpoint
                    logger.warning(
                        "[chat.pre_tool_retry] model=%s lane=%s retry=%s/%s iteration=%s error=%s",
                        effective_chat_config.model_name,
                        queue_lane,
                        pre_tool_failure_count,
                        max_pre_tool_retries,
                        iteration,
                        exc,
                    )
                    await emit_webchat_stage("retrying_model", str(exc))
                    continue
                logger.exception(
                    "[chat.suppressed_error] model=%s lane=%s iteration=%s error=%s",
                    effective_chat_config.model_name,
                    queue_lane,
                    iteration,
                    exc,
                )
                return ""

        logger.warning("[AI决策] 达到最大迭代次数，未能完成处理")
        return "达到最大迭代次数，未能完成处理"
