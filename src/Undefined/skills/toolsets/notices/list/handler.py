from typing import Any, Dict, List
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def parse_timestamp(time_str: str) -> int:
    """解析时间字符串为时间戳"""
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        return int(dt.timestamp())
    except Exception:
        return 0


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    group_id = args.get("group_id")
    if not group_id:
        # 优先从 context 获取（避免并发问题）
        group_id = context.get("group_id")
    if not group_id:
        # 向后兼容
        ai_client = context.get("ai_client")
        group_id = ai_client.current_group_id if ai_client else None

    if not group_id:
        return "未能确定群聊 ID，请提供 group_id 参数或在群聊中调用"

    sender = context.get("sender")
    if not sender or not hasattr(sender, "onebot"):
        return "OneBot 客户端未连接"

    try:
        notices = await sender.onebot._get_group_notices(group_id)
        if not notices:
            return f"群 {group_id} 暂无公告"

        # 筛选逻辑
        filtered_notices: List[Dict[str, Any]] = []
        keyword = args.get("keyword", "").lower()
        start_ts = parse_timestamp(args.get("start_time", ""))
        end_ts = parse_timestamp(args.get("end_time", "")) or float("inf")

        for notice in notices:
            # 统一字段提取
            content = notice.get("content") or notice.get("text")
            if not content and isinstance(notice.get("message"), dict):
                content = notice["message"].get("text") or notice["message"].get(
                    "content"
                )
            content = content or "无内容"

            pub_time_ts = int(
                notice.get("pub_time")
                or notice.get("publish_time")
                or notice.get("time", 0)
            )

            # 关键词过滤
            if keyword and keyword not in content.lower():
                continue

            # 时间过滤
            if pub_time_ts < start_ts or pub_time_ts > end_ts:
                continue

            filtered_notices.append(
                {
                    "content": content,
                    "pub_time_ts": pub_time_ts,
                    "sender_id": notice.get("sender_id")
                    or notice.get("uin")
                    or notice.get("user_id", "未知"),
                    "notice_id": notice.get("notice_id", "未知"),
                }
            )

        if not filtered_notices:
            return "根据您的筛选条件未找到匹配的公告"

        # 排序（按时间倒序）
        filtered_notices.sort(key=lambda x: x["pub_time_ts"], reverse=True)

        # 数量限制
        is_all = args.get("all", False)
        if not is_all:
            count = args.get("count", 5)
            display_notices = filtered_notices[:count]
        else:
            display_notices = filtered_notices

        lines = [f"群 {group_id} 公告列表（共 {len(filtered_notices)} 条匹配）："]
        for i, notice in enumerate(display_notices):
            pub_time = datetime.fromtimestamp(notice["pub_time_ts"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            lines.append(
                f"{i + 1}. [{pub_time}] [ID: {notice['notice_id']}] 发布者({notice['sender_id']}):\n{notice['content']}"
            )
            lines.append("-" * 20)

        if not is_all and len(filtered_notices) > len(display_notices):
            lines.append(
                f"... 还有 {len(filtered_notices) - len(display_notices)} 条公告未显示，可使用 notices.list(all=True) 查看全部"
            )

        return "\n".join(lines)
    except Exception as e:
        logger.exception(f"[群公告] 获取群 {group_id} 公告列表失败: {e}")
        return f"获取群公告失败: {e}"
