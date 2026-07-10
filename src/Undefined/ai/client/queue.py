"""AI 客户端队列化 LLM 调用与摘要请求。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from Undefined.ai.parsing import extract_choices_content
from Undefined.ai.queue_budget import (
    compute_queued_llm_timeout_seconds,
    resolve_effective_retry_count,
)
from Undefined.context import RequestContext
import Undefined.ai.client as ai_client_module
from Undefined.services.queue_manager import (
    ALL_QUEUE_LANES,
    QUEUE_LANE_BACKGROUND,
    QUEUE_LANE_GROUP_MENTION,
    QUEUE_LANE_GROUP_NORMAL,
    QUEUE_LANE_GROUP_SUPERADMIN,
    QUEUE_LANE_PRIVATE,
    QUEUE_LANE_SUPERADMIN,
)

from Undefined.ai.client.setup import ClientSetupMixin

logger = logging.getLogger(__name__)


class ClientQueueMixin(ClientSetupMixin):
    """统一队列 LLM 调用与会话摘要投递。"""

    def _resolve_queue_lane(self, queue_lane: Any = None) -> str:
        # 优先级：显式参数 > RequestContext 资源 > 按会话类型推断 > 后台
        queue_lane_text = str(queue_lane or "").strip().lower()
        if queue_lane_text in ALL_QUEUE_LANES:
            return queue_lane_text

        ctx = RequestContext.current()
        if ctx is not None:
            ctx_lane = str(ctx.get_resource("queue_lane") or "").strip().lower()
            if ctx_lane in ALL_QUEUE_LANES:
                return ctx_lane

            runtime_config = self._get_runtime_config()
            superadmin_qq = int(getattr(runtime_config, "superadmin_qq", 0) or 0)
            if ctx.request_type == "private":
                if superadmin_qq > 0 and (
                    ctx.user_id == superadmin_qq or ctx.sender_id == superadmin_qq
                ):
                    return QUEUE_LANE_SUPERADMIN
                return QUEUE_LANE_PRIVATE
            if ctx.request_type == "group":
                if superadmin_qq > 0 and ctx.sender_id == superadmin_qq:
                    return QUEUE_LANE_GROUP_SUPERADMIN
                # @bot 走 mention 队列，与普通群聊隔离
                if bool(ctx.get_resource("is_at_bot")):
                    return QUEUE_LANE_GROUP_MENTION
                return QUEUE_LANE_GROUP_NORMAL

        return QUEUE_LANE_BACKGROUND

    def _get_queued_llm_wait_timeout_seconds(self) -> float:
        retry_count = resolve_effective_retry_count(
            self._get_runtime_config(),
            getattr(self, "_queue_manager", None),
        )
        return compute_queued_llm_timeout_seconds(
            self._get_runtime_config(),
            self.chat_config,
            retry_count=retry_count,
        )

    async def submit_queued_llm_call(
        self,
        model_config: Any,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = "auto",
        call_type: str = "background",
        max_tokens: int | None = None,
        transport_state: dict[str, Any] | None = None,
        queue_lane: str | None = None,
        skip_prefetch_tools: bool = False,
    ) -> dict[str, Any]:
        """将 LLM 调用投递到统一队列，走统一发车间隔和重试逻辑。
        无 queue_manager 时降级为直接调用。"""
        effective_max_tokens = (
            max_tokens
            if max_tokens is not None
            else getattr(model_config, "max_tokens", 4096)
        )
        resolved_queue_lane = self._resolve_queue_lane(queue_lane)
        # 无队列管理器时直接请求，跳等车/重试封装
        if self._queue_manager is None:
            return await self.request_model(
                model_config=model_config,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                call_type=call_type,
                max_tokens=effective_max_tokens,
                transport_state=transport_state,
                skip_prefetch_tools=skip_prefetch_tools,
            )
        request_id = uuid4().hex
        event: asyncio.Event = asyncio.Event()
        # 挂起表：QueueManager 回调 set_llm_call_result 时唤醒等待方
        self._pending_llm_calls[request_id] = (event, None)
        model_name = getattr(model_config, "model_name", "default")
        request: dict[str, Any] = {
            "type": "queued_llm_call",
            "request_id": request_id,
            "model_config": model_config,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "call_type": call_type,
            "max_tokens": effective_max_tokens,
            "transport_state": transport_state,
            "skip_prefetch_tools": skip_prefetch_tools,
        }
        ctx = RequestContext.current()
        if ctx is not None:
            if ctx.group_id is not None:
                request["group_id"] = ctx.group_id
            if ctx.user_id is not None:
                request["user_id"] = ctx.user_id
        logger.info(
            "[queued_llm_enqueue] request_id=%s call_type=%s model=%s lane=%s messages=%s tools=%s",
            request_id,
            call_type,
            model_name,
            resolved_queue_lane,
            len(messages),
            bool(tools),
        )
        try:
            receipt = await self._queue_manager.add_queued_llm_request(
                request,
                lane=resolved_queue_lane,
                model_name=model_name,
            )
            wait_timeout = compute_queued_llm_timeout_seconds(
                self._get_runtime_config(),
                model_config,
                retry_count=resolve_effective_retry_count(
                    self._get_runtime_config(), self._queue_manager
                ),
                initial_wait_seconds=float(
                    getattr(receipt, "estimated_wait_seconds", 0.0) or 0.0
                ),
                # 首次 dispatch 间隔已含在 estimated_wait 中，避免重复计入
                include_first_dispatch_interval=False,
            )
            try:
                await asyncio.wait_for(event.wait(), timeout=wait_timeout)
            except asyncio.TimeoutError:
                logger.exception(
                    "[queued_llm_wait_timeout] request_id=%s call_type=%s model=%s lane=%s timeout=%.1fs",
                    request_id,
                    call_type,
                    model_name,
                    resolved_queue_lane,
                    wait_timeout,
                )
                raise
        finally:
            entry = self._pending_llm_calls.pop(request_id, None)
        _, result = entry if entry is not None else (None, None)
        if isinstance(result, Exception):
            raise result
        return result or {}

    async def submit_background_llm_call(
        self,
        model_config: Any,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = "auto",
        call_type: str = "background",
        max_tokens: int | None = None,
        transport_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """后台 LLM 提交兼容包装。"""
        return await self.submit_queued_llm_call(
            model_config=model_config,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            call_type=call_type,
            max_tokens=max_tokens,
            transport_state=transport_state,
            queue_lane=QUEUE_LANE_BACKGROUND,
        )

    def set_llm_call_result(
        self, request_id: str, result: dict[str, Any] | Exception
    ) -> None:
        entry = self._pending_llm_calls.get(request_id)
        if entry is None:
            return
        event, _ = entry
        self._pending_llm_calls[request_id] = (event, result)
        event.set()

    async def _summarize_message_history_queued(
        self,
        messages_text: str,
        instruction: str = "",
    ) -> str:
        model_config = self._resolve_summary_model_for_requests()
        built_messages = await self._summary_service.build_message_summary_messages(
            # messages_text, instruction
            messages_text,
            instruction,
        )
        result = await self.submit_queued_llm_call(
            model_config=model_config,
            messages=built_messages,
            tools=None,
            call_type="message_summary",
            max_tokens=model_config.max_tokens,
        )
        return extract_choices_content(result).strip()

    async def _merge_summaries_queued(self, summaries: list[str]) -> str:
        if len(summaries) == 1:
            return summaries[0]

        model_config = self._resolve_summary_model_for_requests()
        messages = await self._summary_service.build_message_merge_messages(summaries)
        result = await self.submit_queued_llm_call(
            model_config=model_config,
            messages=messages,
            tools=None,
            call_type="merge_message_summaries",
            max_tokens=8192,
        )
        return extract_choices_content(result).strip()

    async def summarize_command_session(
        self,
        history_manager: Any,
        *,
        group_id: int,
        user_id: int,
        count: int | None = None,
        time_range: str | None = None,
        instruction: str = "",
    ) -> str:
        """Fetch session messages and summarize via summary model without tools."""
        messages_text = await ai_client_module.fetch_session_messages(
            history_manager,
            group_id=group_id,
            user_id=user_id,
            count=count,
            time_range=time_range,
            runtime_config=self.runtime_config,
            include_header=False,
        )
        if not messages_text:
            return "当前会话暂无消息记录"
        if messages_text.startswith("无法解析时间范围"):
            return messages_text

        input_budget = await self._summary_service.resolve_message_input_budget(
            instruction
        )
        total_tokens = self.count_tokens(messages_text)
        if total_tokens <= input_budget:
            return await self._summarize_message_history_queued(
                # messages_text, instruction
                messages_text,
                instruction,
            )

        # 超长会话：分块摘要后再合并，避免超出上下文窗口
        chunks = self.split_messages_by_tokens(messages_text, input_budget)
        summaries = [
            await self._summarize_message_history_queued(chunk, instruction)
            for chunk in chunks
        ]
        return await self._merge_summaries_queued(summaries)
