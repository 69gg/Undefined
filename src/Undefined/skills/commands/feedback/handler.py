from __future__ import annotations

import asyncio
import html
import logging
import re
import uuid
from datetime import datetime
from typing import Any, TypedDict, cast

from Undefined.services.commands.context import CommandContext
from Undefined.utils import io
from Undefined.utils.paths import DATA_DIR, RENDER_CACHE_DIR, ensure_dir

logger = logging.getLogger("feedback")

FEEDBACK_FILE = DATA_DIR / "feedback" / "feedback.json"

_FEEDBACK_ID_RE = re.compile(r"^\d{8}-\d+$")
_LIST_LIMIT = 20
_SUMMARY_LIMIT = 80
_STORAGE_LOCK = asyncio.Lock()
_USAGE_TEXT = (
    "用法：/feedback [add|view|del] [内容或ID]\n"
    "示例：/fb 希望增加夜间静默模式\n"
    "查看：/fb 或 /fb 20260509-1\n"
    "删除：/feedback del 20260509-1（需超级管理员）"
)


class FeedbackRecord(TypedDict):
    id: str
    content: str
    scope: str
    group_id: int | None
    user_id: int | None
    sender_id: int
    created_at: str


def _now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def _parse_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_record(raw: Any) -> FeedbackRecord | None:
    if not isinstance(raw, dict):
        return None

    feedback_id = str(raw.get("id") or "").strip()
    content = str(raw.get("content") or "").strip()
    scope = str(raw.get("scope") or "group").strip().lower()
    sender_id = _parse_int_or_none(raw.get("sender_id"))
    created_at = str(raw.get("created_at") or "").strip()

    if not feedback_id or not content or sender_id is None or not created_at:
        return None
    if scope not in {"group", "private"}:
        scope = "group"

    return FeedbackRecord(
        id=feedback_id,
        content=content,
        scope=scope,
        group_id=_parse_int_or_none(raw.get("group_id")),
        user_id=_parse_int_or_none(raw.get("user_id")),
        sender_id=sender_id,
        created_at=created_at,
    )


async def _load_records() -> list[FeedbackRecord]:
    raw = await io.read_json(FEEDBACK_FILE, use_lock=True)
    if raw is None:
        return []

    raw_records: Any
    if isinstance(raw, list):
        raw_records = raw
    elif isinstance(raw, dict) and isinstance(raw.get("records"), list):
        raw_records = raw["records"]
    else:
        logger.warning("[Feedback] 存储文件格式无效，忽略: path=%s", FEEDBACK_FILE)
        return []

    records: list[FeedbackRecord] = []
    for item in cast(list[Any], raw_records):
        record = _normalize_record(item)
        if record is not None:
            records.append(record)
    return records


async def _save_records(records: list[FeedbackRecord]) -> None:
    await io.write_json(FEEDBACK_FILE, records, use_lock=True)


def _next_feedback_id(records: list[FeedbackRecord], now: datetime) -> str:
    date_prefix = now.strftime("%Y%m%d")
    prefix = f"{date_prefix}-"
    max_sequence = 0
    for record in records:
        feedback_id = record["id"]
        if not feedback_id.startswith(prefix):
            continue
        suffix = feedback_id.removeprefix(prefix)
        if suffix.isdigit():
            max_sequence = max(max_sequence, int(suffix))
    return f"{prefix}{max_sequence + 1}"


def _is_superadmin(context: CommandContext) -> bool:
    return context.check_permission("superadmin")


def _source_label(record: FeedbackRecord) -> str:
    return "私聊" if record["scope"] == "private" else "群聊"


def _source_target_label(record: FeedbackRecord) -> str:
    if record["scope"] == "private":
        target = (
            record["user_id"] if record["user_id"] is not None else record["sender_id"]
        )
        return f"私聊用户 ID: {target}"
    target = record["group_id"] if record["group_id"] is not None else 0
    return f"群号: {target}"


def _summary(content: str, limit: int = _SUMMARY_LIMIT) -> str:
    text = " ".join(content.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _find_record(
    records: list[FeedbackRecord], feedback_id: str
) -> FeedbackRecord | None:
    for record in records:
        if record["id"] == feedback_id:
            return record
    return None


def _record_sort_key(record: FeedbackRecord) -> tuple[str, int]:
    suffix = record["id"].rsplit("-", 1)[-1]
    sequence = int(suffix) if suffix.isdigit() else 0
    return (record["created_at"], sequence)


def _recent_records(records: list[FeedbackRecord]) -> list[FeedbackRecord]:
    return sorted(records, key=_record_sort_key, reverse=True)[:_LIST_LIMIT]


def _format_list_text(records: list[FeedbackRecord], *, is_superadmin: bool) -> str:
    recent = _recent_records(records)
    if not recent:
        return "📭 暂无反馈"

    lines = [f"📋 反馈列表（最近 {len(recent)} 条）", ""]
    for record in recent:
        if is_superadmin:
            lines.append(
                " | ".join(
                    [
                        record["id"],
                        record["created_at"],
                        _source_label(record),
                        f"提交者 QQ: {record['sender_id']}",
                        _source_target_label(record),
                        _summary(record["content"]),
                    ]
                )
            )
        else:
            lines.append(f"- {record['id']} {_summary(record['content'])}")
    lines.append("")
    lines.append("查看详情：/fb <ID>")
    return "\n".join(lines)


def _format_detail_text(record: FeedbackRecord, *, is_superadmin: bool) -> str:
    if not is_superadmin:
        return "\n".join(
            [
                "🧾 反馈详情",
                f"ID: {record['id']}",
                "",
                "内容:",
                record["content"],
            ]
        )

    return "\n".join(
        [
            "🧾 反馈详情",
            f"ID: {record['id']}",
            f"时间: {record['created_at']}",
            f"来源: {_source_label(record)}",
            f"提交者 QQ: {record['sender_id']}",
            _source_target_label(record),
            "",
            "内容:",
            record["content"],
        ]
    )


def _format_list_html(records: list[FeedbackRecord], *, is_superadmin: bool) -> str:
    recent = _recent_records(records)
    title = "反馈列表"
    subtitle = f"最近 {len(recent)} 条"

    if not recent:
        rows = '<div class="empty">暂无反馈</div>'
    elif is_superadmin:
        body_rows = []
        for record in recent:
            body_rows.append(
                "<tr>"
                f"<td>{html.escape(record['id'])}</td>"
                f"<td>{html.escape(record['created_at'])}</td>"
                f"<td>{html.escape(_source_label(record))}</td>"
                f"<td>{record['sender_id']}</td>"
                f"<td>{html.escape(_source_target_label(record))}</td>"
                f"<td>{html.escape(_summary(record['content']))}</td>"
                "</tr>"
            )
        rows = (
            "<table><thead><tr><th>ID</th><th>时间</th><th>来源</th>"
            "<th>提交者 QQ</th><th>目标</th><th>内容摘要</th></tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody></table>"
        )
    else:
        body_rows = []
        for record in recent:
            body_rows.append(
                "<tr>"
                f"<td>{html.escape(record['id'])}</td>"
                f"<td>{html.escape(_summary(record['content']))}</td>"
                "</tr>"
            )
        rows = (
            "<table><thead><tr><th>ID</th><th>内容摘要</th></tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody></table>"
        )

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 24px;
      font-family: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif;
      color: #263238;
      background: #f4f7f6;
    }}
    .panel {{
      width: 100%;
      border: 1px solid #dbe5e2;
      background: #ffffff;
      border-radius: 8px;
      overflow: hidden;
    }}
    .header {{
      padding: 18px 22px;
      border-bottom: 1px solid #dbe5e2;
      background: #eef5f2;
    }}
    h1 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.35;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .subtitle {{
      margin-top: 6px;
      color: #607d75;
      font-size: 14px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid #edf2f0;
      text-align: left;
      vertical-align: top;
      font-size: 14px;
      line-height: 1.55;
      word-break: break-word;
    }}
    th {{
      color: #455a64;
      background: #fafcfc;
      font-weight: 700;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    .empty {{
      padding: 28px 22px;
      color: #607d75;
      font-size: 16px;
    }}
  </style>
</head>
<body>
  <div class="panel">
    <div class="header">
      <h1>{html.escape(title)}</h1>
      <div class="subtitle">{html.escape(subtitle)}</div>
    </div>
    {rows}
  </div>
</body>
</html>"""


async def _send_message(context: CommandContext, message: str) -> None:
    if context.scope == "private":
        user_id = int(context.user_id or context.sender_id)
        await context.sender.send_private_message(user_id, message)
        return
    await context.sender.send_group_message(context.group_id, message)


async def _send_rendered_list(
    context: CommandContext,
    records: list[FeedbackRecord],
    *,
    is_superadmin: bool,
) -> None:
    from Undefined.render import render_html_to_image

    output_dir = ensure_dir(RENDER_CACHE_DIR)
    output_path = output_dir / f"feedback_{uuid.uuid4().hex[:8]}.png"
    html_content = _format_list_html(records, is_superadmin=is_superadmin)
    await render_html_to_image(html_content, str(output_path), viewport_width=760)
    await _send_message(context, f"[CQ:image,file={output_path.resolve().as_uri()}]")


async def _handle_add(args: list[str], context: CommandContext) -> None:
    content = " ".join(arg.strip() for arg in args).strip()
    if not content:
        await _send_message(context, "❌ 反馈内容不能为空\n" + _USAGE_TEXT)
        return

    async with _STORAGE_LOCK:
        records = await _load_records()
        now = _now()
        feedback_id = _next_feedback_id(records, now)
        record = FeedbackRecord(
            id=feedback_id,
            content=content,
            scope="private" if context.scope == "private" else "group",
            group_id=context.group_id if context.scope != "private" else None,
            user_id=int(context.user_id or context.sender_id)
            if context.scope == "private"
            else None,
            sender_id=context.sender_id,
            created_at=now.isoformat(),
        )
        records.append(record)
        await _save_records(records)

    await _send_message(context, f"✅ 已收到反馈：{feedback_id}")


async def _handle_view(args: list[str], context: CommandContext) -> None:
    records = await _load_records()
    is_superadmin = _is_superadmin(context)

    if args:
        feedback_id = args[0].strip()
        if not _FEEDBACK_ID_RE.fullmatch(feedback_id):
            await _send_message(context, "❌ 反馈 ID 格式不正确，例如：20260509-1")
            return
        record = _find_record(records, feedback_id)
        if record is None:
            await _send_message(context, f"❌ 反馈不存在：{feedback_id}")
            return
        await _send_message(
            context, _format_detail_text(record, is_superadmin=is_superadmin)
        )
        return

    try:
        await _send_rendered_list(context, records, is_superadmin=is_superadmin)
    except Exception:
        logger.exception("[Feedback] 渲染反馈列表失败，回退纯文本")
        await _send_message(
            context, _format_list_text(records, is_superadmin=is_superadmin)
        )


async def _handle_delete(args: list[str], context: CommandContext) -> None:
    if not context.check_permission("superadmin"):
        await _send_message(context, "❌ 仅超级管理员可以删除反馈")
        return
    if not args:
        await _send_message(context, "❌ 用法：/feedback del <ID>")
        return

    feedback_id = args[0].strip()
    if not _FEEDBACK_ID_RE.fullmatch(feedback_id):
        await _send_message(context, "❌ 反馈 ID 格式不正确，例如：20260509-1")
        return

    async with _STORAGE_LOCK:
        records = await _load_records()
        record = _find_record(records, feedback_id)
        if record is None:
            await _send_message(context, f"❌ 反馈不存在：{feedback_id}")
            return
        remaining = [item for item in records if item["id"] != feedback_id]
        await _save_records(remaining)

    await _send_message(context, f"✅ 已删除反馈：{feedback_id}")


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /feedback。分发层会把推断后的参数改写为 [子命令, *参数]。"""
    if not args:
        await _handle_view([], context)
        return

    subcommand = args[0].strip().lower()
    sub_args = args[1:]

    if subcommand == "add":
        await _handle_add(sub_args, context)
    elif subcommand == "view":
        await _handle_view(sub_args, context)
    elif subcommand == "del":
        await _handle_delete(sub_args, context)
    else:
        await _send_message(context, _USAGE_TEXT)
