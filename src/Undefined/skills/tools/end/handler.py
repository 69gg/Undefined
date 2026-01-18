from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    summary = args.get("summary", "")
    if summary:
        end_summaries = context.get("end_summaries")
        if end_summaries is not None:
            end_summaries.append(summary)
            logger.info(f"保存end记录: {summary[:50]}...")

            # 持久化保存
            end_summary_storage = context.get("end_summary_storage")
            if end_summary_storage:
                # 转换 deque 为 list 进行序列化
                end_summary_storage.save(list(end_summaries))

    # 通知调用方对话应结束
    context["conversation_ended"] = True

    return "对话已结束"
