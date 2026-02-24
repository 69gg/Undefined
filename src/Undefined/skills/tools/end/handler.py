from collections import deque
from typing import Any, Dict
import logging
import re

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
_CONTENT_TAG_RE = re.compile(
    r"<message\b[^>]*>\s*<content>(?P<content>.*?)</content>\s*</message>",
    re.DOTALL | re.IGNORECASE,
)
_DEFAULT_HISTORIAN_TEXT_LEN = 800
_DEFAULT_HISTORIAN_LINES = 12
_DEFAULT_HISTORIAN_LINE_LEN = 240
_MIN_HISTORIAN_TEXT_LEN = 16
_MAX_HISTORIAN_TEXT_LEN = 4000
_MIN_HISTORIAN_LINES = 0
_MAX_HISTORIAN_LINES = 50
_MIN_HISTORIAN_LINE_LEN = 16
_MAX_HISTORIAN_LINE_LEN = 1000


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


def _clip_text(value: Any, max_len: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp_int(value: int, min_value: int, max_value: int) -> int:
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def _resolve_historian_limits(context: Dict[str, Any]) -> tuple[int, int, int]:
    max_source_len = _DEFAULT_HISTORIAN_TEXT_LEN
    recent_k = _DEFAULT_HISTORIAN_LINES
    max_recent_line_len = _DEFAULT_HISTORIAN_LINE_LEN

    runtime_config = context.get("runtime_config")
    cognitive = getattr(runtime_config, "cognitive", None) if runtime_config else None
    if cognitive is not None:
        max_source_len = _safe_int(
            getattr(cognitive, "historian_source_message_max_len", max_source_len),
            max_source_len,
        )
        recent_k = _safe_int(
            getattr(cognitive, "historian_recent_messages_inject_k", recent_k),
            recent_k,
        )
        max_recent_line_len = _safe_int(
            getattr(
                cognitive, "historian_recent_message_line_max_len", max_recent_line_len
            ),
            max_recent_line_len,
        )

    max_source_len = _clamp_int(
        max_source_len, _MIN_HISTORIAN_TEXT_LEN, _MAX_HISTORIAN_TEXT_LEN
    )
    recent_k = _clamp_int(recent_k, _MIN_HISTORIAN_LINES, _MAX_HISTORIAN_LINES)
    max_recent_line_len = _clamp_int(
        max_recent_line_len, _MIN_HISTORIAN_LINE_LEN, _MAX_HISTORIAN_LINE_LEN
    )
    return max_source_len, recent_k, max_recent_line_len


def _extract_current_content_from_question(question: str, *, max_len: int) -> str:
    text = str(question or "").strip()
    if not text:
        return ""
    matched = _CONTENT_TAG_RE.search(text)
    if matched:
        return _clip_text(matched.group("content"), max_len)
    return _clip_text(text, max_len)


def _build_historian_recent_messages(
    context: Dict[str, Any], *, recent_k: int, max_line_len: int
) -> list[str]:
    if recent_k <= 0:
        return []

    history_manager = context.get("history_manager")
    if history_manager is None or not hasattr(history_manager, "get_recent"):
        return []

    request_type = str(context.get("request_type") or "").strip().lower()
    if request_type == "group":
        chat_id = str(context.get("group_id") or "").strip()
        msg_type = "group"
    elif request_type == "private":
        chat_id = str(context.get("user_id") or context.get("sender_id") or "").strip()
        msg_type = "private"
    else:
        return []

    if not chat_id:
        return []

    try:
        recent = history_manager.get_recent(chat_id, msg_type, 0, recent_k)
    except Exception as exc:
        logger.warning(
            "[end工具] 获取近期历史失败: chat=%s type=%s err=%s", chat_id, msg_type, exc
        )
        return []

    if not isinstance(recent, list):
        return []

    lines: list[str] = []
    for msg in recent:
        if not isinstance(msg, dict):
            continue
        timestamp = str(msg.get("timestamp", "")).strip()
        display_name = str(msg.get("display_name", "")).strip()
        user_id = str(msg.get("user_id", "")).strip()
        message_text = _clip_text(msg.get("message", ""), max_line_len)
        if not message_text:
            continue
        who = display_name or (f"UID:{user_id}" if user_id else "未知用户")
        if user_id:
            who = f"{who}({user_id})"
        if timestamp:
            lines.append(f"[{timestamp}] {who}: {message_text}")
        else:
            lines.append(f"{who}: {message_text}")
    return lines[-recent_k:]


def _inject_historian_reference_context(context: Dict[str, Any]) -> None:
    max_source_len, recent_k, max_recent_line_len = _resolve_historian_limits(context)
    current_question = str(context.get("current_question") or "").strip()
    source_message = _extract_current_content_from_question(
        current_question, max_len=max_source_len
    )
    if source_message:
        context["historian_source_message"] = source_message
    elif current_question:
        context["historian_source_message"] = _clip_text(
            current_question, max_source_len
        )

    recent_lines = _build_historian_recent_messages(
        context, recent_k=recent_k, max_line_len=max_recent_line_len
    )
    if recent_lines:
        context["historian_recent_messages"] = recent_lines


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
        _inject_historian_reference_context(context)
        job_id = await cognitive_service.enqueue_job(
            action_summary=action_summary,
            new_info=new_info,
            context=context,
            force=force,
        )
        logger.info("[end工具] 认知记忆任务已提交: job_id=%s", job_id or "")
    elif cognitive_service:
        logger.info("[end工具] 记忆字段均为空，跳过认知入队")

    # 通知调用方对话应结束
    context["conversation_ended"] = True

    return "对话已结束"
