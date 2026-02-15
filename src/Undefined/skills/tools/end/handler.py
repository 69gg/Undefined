from collections import deque
from typing import Any, Dict
import logging

from Undefined.end_summary_storage import (
    EndSummaryLocation,
    EndSummaryRecord,
    EndSummaryStorage,
    MAX_END_SUMMARIES,
)

logger = logging.getLogger(__name__)


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
    summary_raw = args.get("summary", "")
    summary = summary_raw.strip() if isinstance(summary_raw, str) else ""

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

    # 通知调用方对话应结束
    context["conversation_ended"] = True

    return "对话已结束"
