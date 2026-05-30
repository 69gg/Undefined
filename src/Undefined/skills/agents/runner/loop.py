# Agent LLM↔工具迭代循环核心
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from Undefined.ai.transports.openai_transport import RESPONSES_OUTPUT_ITEMS_KEY
from Undefined.skills.agents.runner.context import prepare_agent_run
from Undefined.skills.agents.runner.tools import execute_assistant_tool_calls


def _webchat_agent_path(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _webchat_depth(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


async def _emit_webchat_agent_stage(
    context: dict[str, Any],
    agent_name: str,
    stage: str,
    detail: Any | None = None,
) -> None:
    callback = context.get("webchat_event_callback")
    if not callable(callback):
        return
    call_id = str(context.get("webchat_parent_call_id") or "").strip()
    if not call_id:
        return
    parent_call_id = str(context.get("webchat_call_parent_id") or "").strip()
    payload: dict[str, Any] = {
        "webchat_call_id": call_id,
        "parent_webchat_call_id": parent_call_id,
        "agent_name": agent_name,
        "name": agent_name,
        "stage": stage,
        "depth": _webchat_depth(context.get("webchat_depth")),
        "agent_path": _webchat_agent_path(context.get("webchat_agent_path")),
    }
    if detail is not None:
        payload["detail"] = detail
    await callback("agent_stage", payload)


# Agent 主循环：LLM 决策 → 工具执行 → 结果回填
async def run_agent_with_tools(
    *,
    agent_name: str,
    user_content: str,
    context_messages: list[dict[str, str]] | None = None,
    empty_user_content_message: str,
    default_prompt: str,
    context: dict[str, Any],
    agent_dir: Path,
    logger: logging.Logger,
    max_iterations: int = 20,
    tool_error_prefix: str = "错误",
) -> str:
    """执行通用 Agent 循环。

    该方法统一处理：
    - prompt 加载
    - LLM 迭代决策
    - tool call 并发执行
    - tool 结果回填 messages
    """

    # 空输入直接返回提示
    if not user_content.strip():
        return empty_user_content_message

    prepared = await prepare_agent_run(
        agent_name=agent_name,
        user_content=user_content,
        context_messages=context_messages,
        default_prompt=default_prompt,
        context=context,
        agent_dir=agent_dir,
        logger=logger,
    )
    # prepare 失败时 prepared 为错误字符串
    if isinstance(prepared, str):
        return prepared

    await _emit_webchat_agent_stage(context, agent_name, "context_ready")
    messages = prepared.messages
    transport_state: dict[str, Any] | None = None
    pre_tool_failure_count = 0

    # Agent 主循环：LLM 决策 → 工具执行 → 结果回填，直到无 tool_calls
    # 迭代上限防止无限 tool 循环
    for iteration in range(1, max_iterations + 1):
        logger.debug("[Agent:%s] iteration=%s", agent_name, iteration)
        # 记录 checkpoint，pre-tool 失败时可回滚 messages / transport_state
        message_checkpoint_len = len(messages)
        transport_state_checkpoint = transport_state
        try:
            await _emit_webchat_agent_stage(
                context,
                agent_name,
                "waiting_model",
                f"iteration={iteration} model={prepared.agent_config.model_name}",
            )
            # 通过队列提交 LLM 请求（含 tools 与 transport 多轮状态）
            result = await prepared.ai_client.submit_queued_llm_call(
                model_config=prepared.agent_config,
                messages=messages,
                max_tokens=prepared.agent_config.max_tokens,
                call_type=f"agent:{agent_name}",
                tools=prepared.tools if prepared.tools else None,
                tool_choice="auto",
                transport_state=transport_state,
                queue_lane=prepared.queue_lane,
            )
        except Exception as exc:
            logger.exception(
                "[Agent:%s] queued LLM 调用失败: lane=%s iteration=%s error=%s",
                agent_name,
                prepared.queue_lane,
                iteration,
                exc,
            )
            raise RuntimeError("智能体模型请求失败") from exc

        try:
            tool_execution_started = False
            tool_name_map = (
                result.get("_tool_name_map") if isinstance(result, dict) else None
            )
            # API 工具名与内部 registry 名称的映射（含 dot 分隔符转换）
            api_to_internal: dict[str, str] = {}
            if isinstance(tool_name_map, dict):
                raw_api_to_internal = tool_name_map.get("api_to_internal")
                if isinstance(raw_api_to_internal, dict):
                    api_to_internal = {
                        str(key): str(value)
                        for key, value in raw_api_to_internal.items()
                    }

            next_transport_state = (
                result.get("_transport_state") if isinstance(result, dict) else None
            )
            # Responses API 等多轮 transport 状态，下一轮 LLM 调用需回传
            transport_state = (
                next_transport_state if isinstance(next_transport_state, dict) else None
            )

            choice: dict[str, Any] = result.get("choices", [{}])[0]
            message: dict[str, Any] = choice.get("message", {})
            content: str = message.get("content") or ""
            reasoning_content: str | None = message.get("reasoning_content")
            tool_calls: list[dict[str, Any]] = message.get("tool_calls", [])

            # 模型同时返回文本与工具调用时，优先走工具路径
            if content.strip() and tool_calls:
                content = ""

            # 无工具调用即视为最终回复
            if not tool_calls:
                await _emit_webchat_agent_stage(context, agent_name, "done")
                return content

            await _emit_webchat_agent_stage(
                context, agent_name, "preparing_tools", len(tool_calls)
            )
            # 将 assistant 消息（含 tool_calls）追加到对话历史
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            }
            output_items = message.get(RESPONSES_OUTPUT_ITEMS_KEY)
            if isinstance(output_items, list):
                assistant_message[RESPONSES_OUTPUT_ITEMS_KEY] = output_items
            # 部分模型需回放 reasoning_content 以兼容 thinking + tool_call
            capture_reasoning = bool(
                getattr(prepared.agent_config, "thinking_tool_call_compat", False)
            ) or bool(getattr(prepared.agent_config, "reasoning_content_replay", False))
            if capture_reasoning and reasoning_content is not None:
                assistant_message["reasoning_content"] = reasoning_content
            messages.append(assistant_message)

            # 并发执行 tool_calls，结果以 role=tool 消息回填
            tool_names = [
                str(
                    (tool_call.get("function") or {}).get("name")
                    if isinstance(tool_call, dict)
                    and isinstance(tool_call.get("function"), dict)
                    else ""
                )
                for tool_call in tool_calls
            ]
            await _emit_webchat_agent_stage(
                context,
                agent_name,
                "waiting_tools",
                ", ".join(name for name in tool_names if name),
            )
            tool_execution_started = await execute_assistant_tool_calls(
                agent_name=agent_name,
                tool_calls=tool_calls,
                api_to_internal=api_to_internal,
                messages=messages,
                tool_registry=prepared.tool_registry,
                agent_skill_registry=prepared.agent_skill_registry,
                context=context,
                logger=logger,
                tool_error_prefix=tool_error_prefix,
            )
            pre_tool_failure_count = 0

        except Exception as exc:
            # pre-tool 本地异常：在未开始执行工具前可重试当前 LLM 轮次
            if (
                not tool_execution_started
                and pre_tool_failure_count < prepared.max_pre_tool_retries
            ):
                pre_tool_failure_count += 1
                del messages[message_checkpoint_len:]
                transport_state = transport_state_checkpoint
                logger.warning(
                    "[Agent:%s] pre-tool 本地失败，重试当前 LLM 轮次: lane=%s retry=%s/%s iteration=%s error=%s",
                    agent_name,
                    prepared.queue_lane,
                    pre_tool_failure_count,
                    prepared.max_pre_tool_retries,
                    iteration,
                    exc,
                )
                await _emit_webchat_agent_stage(
                    context, agent_name, "retrying_model", str(exc)
                )
                continue
            logger.exception(
                "[Agent:%s] 执行失败，已静默抑制: lane=%s iteration=%s error=%s",
                agent_name,
                prepared.queue_lane,
                iteration,
                exc,
            )
            return ""

    await _emit_webchat_agent_stage(context, agent_name, "done")
    return "达到最大迭代次数"
