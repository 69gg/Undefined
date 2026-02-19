from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Any

from Undefined.utils.group_metrics import (
    clamp_int,
    member_display_name,
    parse_member_level,
)

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """统计群成员等级分布。"""
    request_id = str(context.get("request_id", "-"))
    group_id = args.get("group_id") or context.get("group_id")

    if group_id is None:
        return "请提供群号（group_id 参数），或者在群聊中调用"

    try:
        group_id = int(group_id)
    except (TypeError, ValueError):
        return "参数类型错误：group_id 必须是整数"

    include_examples = bool(args.get("include_examples", True))
    example_count = clamp_int(
        args.get("example_count"), default=3, min_value=1, max_value=10
    )

    min_level_raw = args.get("min_level")
    max_level_raw = args.get("max_level")
    min_level: int | None = None
    max_level: int | None = None

    if min_level_raw is not None:
        try:
            min_level = int(min_level_raw)
        except (TypeError, ValueError):
            return "参数类型错误：min_level 必须是整数"
    if max_level_raw is not None:
        try:
            max_level = int(max_level_raw)
        except (TypeError, ValueError):
            return "参数类型错误：max_level 必须是整数"
    if min_level is not None and max_level is not None and min_level > max_level:
        return "参数范围错误：min_level 不能大于 max_level"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "等级分布统计功能不可用（OneBot 客户端未设置）"

    try:
        member_list: list[dict[str, Any]] = await onebot_client.get_group_member_list(
            group_id
        )
        if not member_list:
            return f"未能获取到群 {group_id} 的成员列表"

        level_counter: Counter[int] = Counter()
        unknown_level_members: list[dict[str, Any]] = []
        level_member_samples: dict[int, list[dict[str, Any]]] = defaultdict(list)

        for member in member_list:
            level = parse_member_level(member.get("level"))
            if level is None:
                unknown_level_members.append(member)
                continue
            if min_level is not None and level < min_level:
                continue
            if max_level is not None and level > max_level:
                continue

            level_counter[level] += 1
            if include_examples and len(level_member_samples[level]) < example_count:
                level_member_samples[level].append(member)

        counted_total = sum(level_counter.values())
        if counted_total <= 0 and not unknown_level_members:
            return f"群 {group_id} 暂无可用等级数据"

        lines: list[str] = [f"【群等级分布】群号: {group_id}"]
        lines.append(f"成员总数: {len(member_list)}")
        lines.append(f"已识别等级成员: {counted_total}")
        if unknown_level_members:
            lines.append(f"等级未知成员: {len(unknown_level_members)}")

        if level_counter:
            lines.append("等级分布:")
            for level, amount in sorted(
                level_counter.items(), key=lambda x: x[0], reverse=True
            ):
                rate = (amount / counted_total * 100) if counted_total > 0 else 0.0
                lines.append(f"- Lv.{level}: {amount} 人 ({rate:.1f}%)")

                if include_examples:
                    samples = level_member_samples.get(level, [])
                    if samples:
                        sample_text = "，".join(
                            f"{member_display_name(m)}({m.get('user_id')})"
                            for m in samples
                        )
                        lines.append(f"  示例: {sample_text}")

        if unknown_level_members and include_examples:
            sample_unknown = unknown_level_members[:example_count]
            sample_text = "，".join(
                f"{member_display_name(m)}({m.get('user_id')})" for m in sample_unknown
            )
            lines.append(f"等级未知示例: {sample_text}")

        return "\n".join(lines)
    except Exception as exc:
        logger.exception(
            "统计等级分布失败: group=%s request_id=%s err=%s",
            group_id,
            request_id,
            exc,
        )
        return "统计失败：等级分布服务暂时不可用，请稍后重试"
