"""后台 LLM 任务：stats 分析、队列调用与 Agent 介绍生成。"""

from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Any, cast

from Undefined.services.queue_manager import QUEUE_LANE_BACKGROUND
from Undefined.utils.resources import read_text_resource

if TYPE_CHECKING:
    from Undefined.ai import AIClient
    from Undefined.config import Config
    from Undefined.services.command import CommandDispatcher

logger = logging.getLogger(__name__)


_STATS_ANALYSIS_PROMPT_PATH = "res/prompts/stats_analysis.txt"
_STATS_ANALYSIS_FALLBACK_PROMPT = (
    "你是一位专业的数据分析师。请根据以下 Token 使用统计数据提供分析：\n\n"
    "{data_summary}\n\n"
    "请从整体概况、趋势、模型效率、成本结构、异常点和优化建议进行总结，"
    "语言简洁，建议可执行。"
)


class BackgroundMixin:
    """队列分发入口与后台 LLM 任务执行。"""

    if TYPE_CHECKING:
        ai: AIClient
        config: Config
        command_dispatcher: CommandDispatcher

        async def _execute_auto_reply(self, request: dict[str, Any]) -> None: ...
        async def _execute_private_reply(self, request: dict[str, Any]) -> None: ...

    async def execute_reply(self, request: dict[str, Any]) -> None:
        """执行排队中的回复请求（由 QueueManager 分发调用）

        参数:
            request: 包含请求类型和必要元数据的请求字典
        """
        req_type = request.get("type", "unknown")
        logger.debug("[执行请求] type=%s keys=%s", req_type, list(request.keys()))
        batch_token = request.get("_message_batcher_token")
        # 投机 pre-fire 被新消息 cancel 后，coordinator 在真正执行前跳过旧 token
        if bool(getattr(batch_token, "cancelled", False)):
            logger.info(
                "[MessageBatcher] 跳过已取消的投机请求: type=%s scope=%s sender=%s batch=%s",
                req_type,
                getattr(batch_token, "scope", ""),
                getattr(batch_token, "sender_id", ""),
                getattr(batch_token, "batch_id", ""),
            )
            return
        if req_type == "auto_reply":
            await self._execute_auto_reply(request)
        elif req_type == "private_reply":
            await self._execute_private_reply(request)
        elif req_type == "stats_analysis":
            await self._execute_stats_analysis(request)
        elif req_type == "agent_intro_generation":
            await self._execute_agent_intro_generation(request)
        elif req_type in {"queued_llm_call", "background_llm_call"}:
            await self._execute_queued_llm_call(request)

    async def _execute_stats_analysis(self, request: dict[str, Any]) -> None:
        """执行 stats 命令的 AI 分析"""
        group_id = request["group_id"]
        request_id = request.get("request_id")
        data_summary = request.get("data_summary", "")

        if not request_id:
            logger.warning("[统计分析] 缺少 request_id，群=%s", group_id)
            return
        try:
            prompt_template = _STATS_ANALYSIS_FALLBACK_PROMPT
            try:
                loaded_prompt = read_text_resource(_STATS_ANALYSIS_PROMPT_PATH).strip()
                if loaded_prompt:
                    prompt_template = loaded_prompt
            except Exception as exc:
                logger.warning("[统计分析] 读取提示词失败，使用内置模板: %s", exc)

            if "{data_summary}" not in prompt_template:
                logger.warning(
                    "[统计分析] 提示词缺少 {data_summary} 占位符，自动追加",
                )
                prompt_template = f"{prompt_template}\n\n{{data_summary}}"

            safe_data_summary = str(data_summary).strip() or "暂无统计数据摘要"
            try:
                full_prompt = prompt_template.format(data_summary=safe_data_summary)
            except Exception as exc:
                logger.warning("[统计分析] 提示词渲染失败，使用回退模板: %s", exc)
                full_prompt = _STATS_ANALYSIS_FALLBACK_PROMPT.format(
                    data_summary=safe_data_summary
                )

            messages = [
                {"role": "system", "content": "你是一位专业的数据分析师。"},
                {"role": "user", "content": full_prompt},
            ]

            result = await self.ai.submit_queued_llm_call(
                model_config=self.config.chat_model,
                messages=messages,
                max_tokens=2048,
                call_type="stats_analysis",
                queue_lane=request.get("_queue_lane"),
            )

            choices = result.get("choices", [{}])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                analysis = content.strip()
            else:
                analysis = "AI 分析未能生成结果"

            if not analysis:
                analysis = "AI 分析结果为空，建议稍后重试。"

            logger.info(
                "[统计分析] 分析完成: group=%s length=%s request_id=%s",
                group_id,
                len(analysis),
                request_id,
            )

            if self.command_dispatcher:
                self.command_dispatcher.set_stats_analysis_result(
                    group_id, request_id, analysis
                )

        except Exception as exc:
            logger.exception("[统计分析] AI 分析失败: %s", exc)
            if self.command_dispatcher:
                self.command_dispatcher.set_stats_analysis_result(
                    group_id, request_id, ""
                )

    async def _execute_queued_llm_call(self, request: dict[str, Any]) -> None:
        """执行队列中的 LLM 子请求。"""
        request_id = request.get("request_id", "")
        retry_count = int(request.get("_retry_count", 0) or 0)
        queue_lane = str(request.get("_queue_lane") or QUEUE_LANE_BACKGROUND)
        call_type = str(request.get("call_type", "background") or "background")
        try:
            max_tokens_raw = request.get("max_tokens") or getattr(
                request["model_config"], "max_tokens", 4096
            )
            max_tokens = int(max_tokens_raw) if max_tokens_raw is not None else 4096
            result = await self.ai.request_model(
                model_config=request["model_config"],
                messages=request["messages"],
                tools=request.get("tools"),
                tool_choice=request.get("tool_choice", "auto"),
                call_type=call_type,
                max_tokens=max_tokens,
                transport_state=request.get("transport_state"),
            )
            self.ai.set_llm_call_result(request_id, result)
            if retry_count > 0:
                logger.info(
                    "[queued_llm_retry_success] request_id=%s call_type=%s model=%s lane=%s retry=%s",
                    request_id,
                    call_type,
                    getattr(request["model_config"], "model_name", "default"),
                    queue_lane,
                    retry_count,
                )
        except Exception as exc:
            retry_count = request.get("_retry_count", 0)
            if retry_count >= self.config.ai_request_max_retries:
                self.ai.set_llm_call_result(request_id, exc)
            raise

    async def _execute_agent_intro_generation(self, request: dict[str, Any]) -> None:
        """执行 Agent 自我介绍生成请求"""
        request_id = request.get("request_id")
        agent_name = request.get("agent_name")

        if not request_id or not agent_name:
            logger.warning(
                "[Agent介绍生成] 缺少必要参数: request_id=%s agent_name=%s",
                request_id,
                agent_name,
            )
            return

        try:
            from Undefined.skills.agents.intro_generator import AgentIntroGenerator

            agent_intro_generator = self.ai._agent_intro_generator
            if not isinstance(agent_intro_generator, AgentIntroGenerator):
                logger.error("[Agent介绍生成] 无法获取 AgentIntroGenerator 实例")
                return

            (
                system_prompt,
                user_prompt,
            ) = await agent_intro_generator.get_intro_prompt_and_context(agent_name)

            messages = [
                {"role": "system", "content": system_prompt or "你是一位智能助手。"},
                {"role": "user", "content": user_prompt},
            ]

            result = await self.ai.submit_queued_llm_call(
                model_config=self.ai.agent_config,
                messages=messages,
                max_tokens=agent_intro_generator.config.max_tokens,
                call_type=f"agent:{agent_name}",
                queue_lane=request.get("_queue_lane"),
            )

            choices = result.get("choices", [{}])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                generated_content = content.strip()
            else:
                generated_content = ""

            logger.info(
                "[Agent介绍生成] 生成完成: agent=%s length=%s request_id=%s",
                agent_name,
                len(generated_content),
                request_id,
            )

            agent_intro_generator.set_intro_generation_result(
                request_id, generated_content if generated_content else None
            )

        except Exception as exc:
            logger.exception(
                "[Agent介绍生成] 生成失败: agent=%s error=%s",
                agent_name,
                exc,
            )
            try:
                agent_intro_generator = cast(
                    AgentIntroGenerator, self.ai._agent_intro_generator
                )
                agent_intro_generator.set_intro_generation_result(request_id, None)
            except Exception:
                pass
