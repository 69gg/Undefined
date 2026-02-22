from collections import deque
from typing import Any, Dict
import logging

from Undefined.context import RequestContext
from Undefined.end_summary_storage import (
    EndSummaryLocation,
    EndSummaryRecord,
    EndSummaryStorage,
    MAX_END_SUMMARIES,
)

logger = logging.getLogger(__name__)


def _parse_force_flag(value: Any) -> bool:
    """force 仅接受布尔值，其他类型一律视为 False。"""
    return value if isinstance(value, bool) else False


def _is_true_flag(value: Any) -> bool:
    """上下文标记仅接受布尔 True。"""
    return isinstance(value, bool) and value


def _was_message_sent_this_turn(context: Dict[str, Any]) -> bool:
    if _is_true_flag(context.get("message_sent_this_turn", False)):
        return True

    ctx = RequestContext.current()
    if ctx is None:
        return False
    return _is_true_flag(ctx.get_resource("message_sent_this_turn", False))


def _build_location(context: Dict[str, Any]) -> EndSummaryLocation | None:
    request_type = context.get("request_type")
    if request_type == "group":
        group_name_raw = context.get("group_name")
        if isinstance(group_name_raw, str) and group_name_raw.strip():
            group_name = group_name_raw.strip()
        else:
            group_id = context.get("group_id")
            group_name = f"群{group_id}" if group_id is not None else "未知群聊"
        return {"type": "group", "name": group_name}

    if request_type == "private":
        sender_name_raw = context.get("sender_name")
        if isinstance(sender_name_raw, str) and sender_name_raw.strip():
            sender_name = sender_name_raw.strip()
        else:
            sender_id = context.get("sender_id")
            user_id = context.get("user_id")
            sender_name = str(sender_id or user_id or "未知用户")
        return {"type": "private", "name": sender_name}

    return None


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    action_summary_raw = args.get("action_summary") or args.get("summary", "")
    action_summary = (
        action_summary_raw.strip() if isinstance(action_summary_raw, str) else ""
    )
    new_info_raw = args.get("new_info", "")
    new_info = new_info_raw.strip() if isinstance(new_info_raw, str) else ""
    # 兼容旧版 summary 字段
    summary = action_summary
    force_raw = args.get("force", False)
    force = _parse_force_flag(force_raw)
    if "force" in args and not isinstance(force_raw, bool):
        logger.warning(
            "[end工具] force 参数类型非法，已按 False 处理: type=%s request_id=%s",
            type(force_raw).__name__,
            context.get("request_id", "-"),
        )

    # 检查：如果有 summary 但本轮未发送消息，且未强制执行，则拒绝
    if summary and not force:
        message_sent = _was_message_sent_this_turn(context)
        if not message_sent:
            logger.warning(
                "[end工具] 拒绝执行：有 summary 但本轮未发送消息，request_id=%s",
                context.get("request_id", "-"),
            )
            return (
                "拒绝结束对话：你记录了 summary 但本轮未发送任何消息或媒体内容。"
                "请先发送消息给用户，或者如果确实不需要发送，请使用 force=true 参数强制结束。"
                "如果你本轮没有做任何事，若无必要，建议不加summary参数，避免记忆噪声。"
            )

    if summary:
        location = _build_location(context)
        record: EndSummaryRecord | None = None
        end_summary_storage = context.get("end_summary_storage")
        if isinstance(end_summary_storage, EndSummaryStorage):
            record = await end_summary_storage.append_summary(
                summary, location=location
            )
        elif end_summary_storage is not None:
            logger.warning(
                "[end工具] end_summary_storage 类型异常: %s", type(end_summary_storage)
            )

        if record is None:
            record = EndSummaryStorage.make_record(summary, location=location)

        end_summaries = context.get("end_summaries")
        if end_summaries is not None:
            if isinstance(end_summaries, deque):
                end_summaries.append(record)
            elif isinstance(end_summaries, list):
                end_summaries.append(record)
                del end_summaries[:-MAX_END_SUMMARIES]
            else:
                logger.warning(
                    "[end工具] end_summaries 类型异常: %s", type(end_summaries)
                )

        logger.info("保存end记录: %s...", summary[:50])

    # 若 cognitive 启用，入队 memory_job
    cognitive_service = context.get("cognitive_service")
    if cognitive_service and action_summary:
        job_id = await cognitive_service.enqueue_job(
            action_summary=action_summary,
            new_info=new_info,
            context=context,
        )
        logger.info("[end工具] 认知记忆任务已提交: job_id=%s", job_id or "")

    # 通知调用方对话应结束
    context["conversation_ended"] = True

    return "对话已结束"
