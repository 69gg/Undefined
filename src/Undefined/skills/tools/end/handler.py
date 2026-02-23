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

_TRUE_BOOL_TOKENS = {"1", "true", "yes", "y", "on"}
_FALSE_BOOL_TOKENS = {"0", "false", "no", "n", "off", ""}


def _coerce_bool(value: Any) -> tuple[bool, bool]:
    """宽松布尔解析。

    返回:
        (parsed_value, recognized)
    """
    if isinstance(value, bool):
        return value, True

    if isinstance(value, int):
        return value != 0, True

    if isinstance(value, str):
        token = value.strip().lower()
        if token in _TRUE_BOOL_TOKENS:
            return True, True
        if token in _FALSE_BOOL_TOKENS:
            return False, True

    return False, False


def _parse_force_flag(value: Any) -> tuple[bool, bool]:
    """force 支持宽松布尔解析（字符串大小写、0/1 等）。"""
    return _coerce_bool(value)


def _is_true_flag(value: Any) -> bool:
    """上下文标记采用宽松布尔解析。"""
    parsed, _recognized = _coerce_bool(value)
    return parsed


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


def _build_record_key(
    context: Dict[str, Any],
    *,
    action_summary: str,
    new_info: list[str],
    perspective: str,
) -> tuple[Any, ...]:
    return (
        str(context.get("request_id", "")).strip(),
        str(context.get("trigger_message_id", "")).strip(),
        str(context.get("request_type", "")).strip(),
        str(context.get("group_id", "")).strip(),
        str(context.get("sender_id") or context.get("user_id") or "").strip(),
        perspective.strip(),
        action_summary.strip(),
        tuple(new_info),
    )


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    action_summary_raw = args.get("action_summary") or args.get("summary", "")
    action_summary = (
        action_summary_raw.strip() if isinstance(action_summary_raw, str) else ""
    )
    new_info_raw = args.get("new_info", [])
    if isinstance(new_info_raw, str):
        new_info = [new_info_raw.strip()] if new_info_raw.strip() else []
    elif isinstance(new_info_raw, list):
        new_info = [str(item).strip() for item in new_info_raw if str(item).strip()]
    else:
        new_info = []
    perspective_raw = args.get("perspective", "")
    perspective = perspective_raw.strip() if isinstance(perspective_raw, str) else ""
    # 兼容旧版 summary 字段
    summary = action_summary
    force_raw = args.get("force", False)
    force, force_recognized = _parse_force_flag(force_raw)
    if "force" in args and not force_recognized:
        logger.warning(
            "[end工具] force 参数无法识别，已按 False 处理: value=%r type=%s request_id=%s",
            force_raw,
            type(force_raw).__name__,
            context.get("request_id", "-"),
        )

    record_key = _build_record_key(
        context,
        action_summary=action_summary,
        new_info=new_info,
        perspective=perspective,
    )
    if context.get("_end_last_record_key") == record_key:
        logger.info(
            "[end工具] 轻量去重命中，跳过重复记录: request_id=%s trigger_message_id=%s perspective=%s",
            context.get("request_id", "-"),
            context.get("trigger_message_id", "-"),
            perspective or "default",
        )
        context["conversation_ended"] = True
        return "对话已结束（重复记录已跳过）"
    context["_end_last_record_key"] = record_key

    # action_summary 非空且本轮未发送消息时拒绝（force=true 可跳过）
    if summary and not force and not _was_message_sent_this_turn(context):
        logger.warning(
            "[end工具] 拒绝执行：本轮未发送消息，request_id=%s",
            context.get("request_id", "-"),
        )
        return (
            "拒绝结束对话：你填写了 action_summary（本轮行动记录）但本轮未发送任何消息或媒体内容。"
            "请先发送消息给用户，或使用 force=true 强制结束。"
            "若本轮确实未做任何事，建议留空 action_summary 以避免记忆噪声。"
            "若你获取到了新信息，考虑填写 new_info 字段以保存这些信息，而不是放在 action_summary 里。"
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
    else:
        logger.info("[end工具] action_summary 为空，跳过 end 摘要写入")

    # 若 cognitive 启用，入队 memory_job
    cognitive_service = context.get("cognitive_service")
    if perspective:
        context["memory_perspective"] = perspective
    if cognitive_service and (action_summary or new_info):
        job_id = await cognitive_service.enqueue_job(
            action_summary=action_summary,
            new_info=new_info,
            context=context,
        )
        logger.info("[end工具] 认知记忆任务已提交: job_id=%s", job_id or "")
    elif cognitive_service:
        logger.info("[end工具] 记忆字段均为空，跳过认知入队")

    # 通知调用方对话应结束
    context["conversation_ended"] = True

    return "对话已结束"
