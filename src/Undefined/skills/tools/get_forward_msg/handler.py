from typing import Any, Dict
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    message_id = args.get("message_id")
    if not message_id:
        return "错误：message_id 不能为空"

    get_forward_msg_callback = context.get("get_forward_msg_callback")
    if not get_forward_msg_callback:
        return "错误：获取合并转发消息的回调未设置"

    try:
        nodes = await get_forward_msg_callback(message_id)
        if not nodes:
            return "未能获取到合并转发消息的内容或内容为空"

        logger.info(f"成功获取合并转发内容，节点数: {len(nodes)}")

        formatted_messages = []
        for i, node in enumerate(nodes):
            # 记录第一个节点的结构用于调试
            if i == 0:
                logger.debug(
                    f"合并转发节点示例结构: {json.dumps(node, ensure_ascii=False)[:500]}"
                )

            sender = node.get("sender") or {}
            # 兼容有些实现直接把发送者信息放在节点根部
            sender_name = (
                sender.get("nickname")
                or node.get("nickname")
                or sender.get("card")
                or node.get("card")
                or "未知用户"
            )
            sender_id = sender.get("user_id") or node.get("user_id") or "未知ID"

            node_time = node.get("time")
            if node_time:
                try:
                    timestamp = datetime.fromtimestamp(float(node_time)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                except (ValueError, TypeError):
                    timestamp = str(node_time)
            else:
                timestamp = "未知时间"

            # 激进的内容提取：尝试所有可能的字段
            raw_content = (
                node.get("content") or node.get("message") or node.get("raw_message")
            )

            text_parts = []
            if raw_content is None:
                text_parts.append("(消息内容字段缺失)")
            elif isinstance(raw_content, str):
                text_parts.append(raw_content)
            elif isinstance(raw_content, dict):
                # 单个消息段
                raw_content = [raw_content]

            if isinstance(raw_content, list):
                for segment in raw_content:
                    if isinstance(segment, str):
                        text_parts.append(segment)
                        continue
                    if not isinstance(segment, dict):
                        continue

                    seg_type = segment.get("type")
                    seg_data = segment.get("data", {})

                    if seg_type == "text":
                        text_parts.append(seg_data.get("text", ""))
                    elif seg_type == "at":
                        qq = seg_data.get("qq", "")
                        text_parts.append(f"[@ {qq}]")
                    elif seg_type == "image":
                        file = seg_data.get("file", "") or seg_data.get("url", "")
                        text_parts.append(f"[图片: {file}]")
                    elif seg_type == "forward":
                        inner_id = seg_data.get("id")
                        text_parts.append(f"[合并转发: {inner_id}]")
                    elif seg_type == "reply":
                        text_parts.append("[引用]")
                    elif seg_type == "face":
                        text_parts.append("[表情]")
                    elif seg_type == "json":
                        # 尝试从 JSON 中提取描述
                        try:
                            j_data = json.loads(seg_data.get("data", "{}"))
                            desc = (
                                j_data.get("meta", {})
                                .get("detail", {})
                                .get("desc", "JSON消息")
                            )
                            text_parts.append(f"[{desc}]")
                        except Exception:
                            text_parts.append("[JSON消息]")
                    elif seg_type == "xml":
                        text_parts.append("[XML消息]")
                    elif seg_type:
                        text_parts.append(f"[{seg_type}]")

            text = "".join(text_parts).strip()
            if not text:
                # 如果还是空，把整个节点键名返回给 AI 辅助判断
                keys = list(node.keys())
                text = f"(无法解析内容，节点键名: {keys})"

            # 格式：XML 标准化
            formatted_messages.append(f"""<message sender="{sender_name}" sender_id="{sender_id}" location="合并转发" time="{timestamp}">
<content>{text}</content>
</message>""")

        result = "\n---\n".join(formatted_messages)
        logger.info(
            f"get_forward_msg 处理完成，返回数据样例 (前500字符): {result[:500]}..."
        )
        return result

    except Exception as e:
        logger.exception(f"解析合并转发消息时出错: {e}")
        return f"解析合并转发消息时出错: {str(e)}"
