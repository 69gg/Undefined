from __future__ import annotations

import logging
from typing import Any, Literal

from Undefined.skills.shared import (
    jm_book_attachment_text,
    jm_book_info_text,
    jm_normalize_book_id,
    jm_scope_key,
    jm_send_book,
)

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
    raw_book_id = str(args.get("book_id", "")).strip()
    if not raw_book_id:
        return "book_id 不能为空"

    book_id = jm_normalize_book_id(raw_book_id)
    if book_id is None:
        return f"无法解析禁漫车号: {raw_book_id}（支持 JM350234、350234 或禁漫链接，车号 5-8 位）"

    output_mode = str(args.get("output_mode", "send") or "send").strip().lower()
    if output_mode not in {"send", "uid", "info"}:
        return "output_mode 只能是 send、uid 或 info"

    runtime_config = context.get("runtime_config")

    try:
        if output_mode == "info":
            return await jm_book_info_text(book_id, config=runtime_config)

        if output_mode == "uid":
            if runtime_config is None:
                return "缺少必要的运行时组件（runtime_config）"
            return await jm_book_attachment_text(
                book_id,
                registry=context.get("attachment_registry"),
                scope_key=jm_scope_key(context),
                config=runtime_config,
            )

        target, error = _resolve_target(args, context)
        if error or target is None:
            return f"目标解析失败: {error or '参数错误'}"
        target_type, target_id = target

        sender = context.get("sender")
        if sender is None:
            return "缺少必要的运行时组件（sender）"
        if runtime_config is None:
            return "缺少必要的运行时组件（runtime_config）"

        return await jm_send_book(
            book_id,
            sender=sender,
            target_type=target_type,
            target_id=target_id,
            config=runtime_config,
        )
    except Exception as exc:
        logger.exception("[jm_book] 执行失败: %s", exc)
        return f"禁漫本子处理失败: {exc}"
