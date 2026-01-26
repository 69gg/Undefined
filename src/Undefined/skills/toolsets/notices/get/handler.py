from typing import Any, Dict
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    notice_id = args.get("notice_id")
    if not notice_id:
        return "请提供 notice_id"

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

        target_notice = None
        for notice in notices:
            if notice.get("notice_id") == notice_id:
                target_notice = notice
                break

        if not target_notice:
            return f"未找到 ID 为 {notice_id} 的公告"

        # 统一字段提取
        content = target_notice.get("content") or target_notice.get("text")
        if not content and isinstance(target_notice.get("message"), dict):
            content = target_notice["message"].get("text") or target_notice[
                "message"
            ].get("content")
        content = content or "无内容"

        pub_time_ts = int(
            target_notice.get("pub_time")
            or target_notice.get("publish_time")
            or target_notice.get("time", 0)
        )
        pub_time = datetime.fromtimestamp(pub_time_ts).strftime("%Y-%m-%d %H:%M:%S")
        sender_id = (
            target_notice.get("sender_id")
            or target_notice.get("uin")
            or target_notice.get("user_id", "未知")
        )

        return f"群 {group_id} 公告详情 [ID: {notice_id}]:\n时间: {pub_time}\n发布者: {sender_id}\n内容:\n{content}"

    except Exception as e:
        logger.exception(f"[群公告] 获取群 {group_id} 公告详情失败: {e}")
        return f"获取群公告详情失败: {e}"
