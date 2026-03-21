from __future__ import annotations

import logging
from typing import Any, Literal

from Undefined.arxiv.sender import send_arxiv_paper

logger = logging.getLogger(__name__)


def _resolve_target(
    args: dict[str, Any], context: dict[str, Any]
) -> tuple[tuple[Literal["group", "private"], int] | None, str | None]:
    target_type_raw = args.get("target_type")
    target_id_raw = args.get("target_id")

    if target_type_raw is not None and target_id_raw is not None:
        target_type = str(target_type_raw).strip().lower()
        if target_type not in ("group", "private"):
            return None, "target_type 只能是 group 或 private"
        try:
            target_id = int(target_id_raw)
        except (TypeError, ValueError):
            return None, "target_id 必须是整数"
        return (target_type, target_id), None  # type: ignore[return-value]

    request_type = context.get("request_type")
    if request_type == "group" and context.get("group_id"):
        return ("group", int(context["group_id"])), None
    if request_type == "private" and context.get("user_id"):
        return ("private", int(context["user_id"])), None

    if context.get("group_id"):
        return ("group", int(context["group_id"])), None
    if context.get("user_id"):
        return ("private", int(context["user_id"])), None
    return None, "无法确定目标会话，请提供 target_type 与 target_id"


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    paper_id = str(args.get("paper_id", "")).strip()
    if not paper_id:
        return "paper_id 不能为空"

    target, error = _resolve_target(args, context)
    if error or target is None:
        return f"目标解析失败: {error or '参数错误'}"
    target_type, target_id = target

    sender = context.get("sender")
    if sender is None:
        return "缺少必要的运行时组件（sender）"

    runtime_config = context.get("runtime_config")
    max_file_size = 100
    author_preview_limit = 20
    summary_preview_chars = 1000
    if runtime_config is not None:
        max_file_size = getattr(runtime_config, "arxiv_max_file_size", 100)
        author_preview_limit = getattr(runtime_config, "arxiv_author_preview_limit", 20)
        summary_preview_chars = getattr(
            runtime_config, "arxiv_summary_preview_chars", 1000
        )

    try:
        return await send_arxiv_paper(
            paper_id=paper_id,
            sender=sender,
            target_type=target_type,
            target_id=target_id,
            max_file_size=max_file_size,
            author_preview_limit=author_preview_limit,
            summary_preview_chars=summary_preview_chars,
            context={"request_id": context.get("request_id", "-")},
        )
    except Exception as exc:
        logger.exception("[arxiv_paper] 执行失败: %s", exc)
        return f"论文处理失败: {exc}"
