"""通用工具函数"""

import re
import logging
from typing import Any, Awaitable, Callable, Optional, List, Dict

from Undefined.utils.xml import escape_xml_attr, escape_xml_text

logger = logging.getLogger(__name__)

# --- 常量定义 ---

# 匹配 CQ 码的正则: [CQ:type,arg1=val1,arg2=val2]
CQ_PATTERN = re.compile(r"\[CQ:([a-zA-Z0-9_-]+),?([^\]]*)\]")

# 标点符号和空白字符正则（用于字数统计和触发规则匹配）
# 包含：空白、常见中英文标点
PUNC_PATTERN = re.compile(
    r'[ \t\n\r\f\v\s!"#$%&\'()*+,\-./:;<=>?@\[\\\]^_`{|}~，。！？、；：""\'\'（）【】「」《》—…·]'
)


def _parse_segment(segment: Dict[str, Any], bot_qq: int = 0) -> Optional[str]:
    """解析单个消息段为文本格式 (内部辅助函数)"""
    type_ = segment.get("type", "")
    raw_data = segment.get("data", {})
    data = raw_data if isinstance(raw_data, dict) else {}

    if type_ == "text":
        return str(data.get("text", ""))

    if type_ == "at":
        return _parse_at_segment(data, bot_qq)

    if type_ == "face":
        return "[表情]"

    return _parse_media_segment(type_, data)


def _extract_forward_id(data: Dict[str, Any]) -> str:
    """提取合并转发 ID（兼容不同实现字段）。"""
    forward_id = data.get("id") or data.get("resid") or data.get("message_id")
    return str(forward_id).strip() if forward_id is not None else ""


def _extract_reply_id(data: Dict[str, Any]) -> str:
    """提取回复消息 ID（兼容不同实现字段）。"""
    reply_id = data.get("id") or data.get("message_id")
    return str(reply_id).strip() if reply_id is not None else ""


def _normalize_message_content(message: Any) -> List[Dict[str, Any]]:
    """将 message 归一化为消息段数组（兼容 list/dict/str）。"""
    if isinstance(message, list):
        normalized: List[Dict[str, Any]] = []
        for item in message:
            if isinstance(item, dict):
                normalized.append(item)
            elif isinstance(item, str):
                normalized.extend(message_to_segments(item))
        return normalized

    if isinstance(message, dict):
        return [message]

    if isinstance(message, str):
        return message_to_segments(message)

    return []


def _parse_at_segment(data: Dict[str, Any], bot_qq: int) -> Optional[str]:
    """解析 @ 消息段"""
    qq = data.get("qq", "")
    if bot_qq and str(qq) == str(bot_qq):
        return None
    return f"[@ {qq}]"


def _parse_media_segment(type_: str, data: Dict[str, Any]) -> Optional[str]:
    """解析多媒体文件类消息段 (图片, 文件, 视频, 语音, 音频)"""
    media_types = {
        "image": "图片",
        "file": "文件",
        "video": "视频",
        "record": "语音",
        "audio": "音频",
    }
    if type_ in media_types:
        label = media_types[type_]
        file_val = data.get("file", "") or data.get("url", "")
        return f"[{label}: {str(file_val)}]"

    if type_ == "forward":
        forward_id = _extract_forward_id(data)
        return f"[合并转发: {forward_id}]" if forward_id else "[合并转发]"

    if type_ == "reply":
        reply_id = _extract_reply_id(data)
        return f"[引用: {reply_id}]" if reply_id else "[引用]"

    return None


def extract_text(message_content: List[Dict[str, Any]], bot_qq: int = 0) -> str:
    """提取消息中的文本内容

    参数:
        message_content: 消息内容列表
        bot_qq: 机器人 QQ 号（用于过滤 @ 机器人的内容），默认为 0（不过滤）

    返回:
        提取的文本
    """
    texts: List[str] = []
    for segment in message_content:
        text = _parse_segment(segment, bot_qq)
        if text is not None:
            texts.append(text)

    return "".join(texts).strip()


async def parse_message_content_for_history(
    message_content: List[Dict[str, Any]],
    bot_qq: int,
    get_msg_func: Optional[Callable[[int], Awaitable[Optional[Dict[str, Any]]]]] = None,
) -> str:
    """解析消息内容用于历史记录（支持回复引用和 @ 格式化）

    参数:
        message_content: 消息内容列表
        bot_qq: 机器人 QQ 号
        get_msg_func: 获取消息详情的异步函数（可选，用于处理回复引用）

    返回:
        解析后的文本
    """
    texts: List[str] = []
    for segment in message_content:
        type_ = segment.get("type")
        raw_data = segment.get("data", {})
        data = raw_data if isinstance(raw_data, dict) else {}

        # 1. 处理特殊复杂类型：回复和合并转发
        if type_ == "reply":
            msg_id = _extract_reply_id(data)
            quote_sender = "未知"
            quote_text = ""

            if msg_id and get_msg_func:
                try:
                    reply_msg = await get_msg_func(int(msg_id))
                    if reply_msg:
                        sender = reply_msg.get("sender")
                        if isinstance(sender, dict):
                            quote_sender = str(
                                sender.get("nickname")
                                or sender.get("card")
                                or sender.get("user_id")
                                or "未知"
                            )

                        content = _normalize_message_content(
                            reply_msg.get("message", [])
                        )
                        quote_text = extract_text(content, bot_qq)

                        if not quote_text:
                            raw_message = reply_msg.get("raw_message")
                            if raw_message is not None:
                                raw_content = _normalize_message_content(raw_message)
                                quote_text = extract_text(raw_content, bot_qq)
                except Exception as e:
                    logger.warning(f"获取回复消息失败: {e}")

            if not quote_text:
                quote_text = f"[引用: {msg_id}]" if msg_id else "[引用]"

            texts.append(
                f'<quote sender="{escape_xml_attr(quote_sender)}">'
                f"{escape_xml_text(quote_text)}</quote>\n"
            )
            continue

        if type_ == "forward":
            msg_id = _extract_forward_id(data)
            if msg_id:
                texts.append(f"[合并转发: {msg_id}]")
            else:
                texts.append("[合并转发]")
            continue

        # 2. 调用通用解析器处理普通类型
        text = _parse_segment(segment, bot_qq)
        if text is not None:
            texts.append(text)

    return "".join(texts).strip()


def message_to_segments(message: str) -> List[Dict[str, Any]]:
    """将包含 CQ 码的字符串转换为 OneBot 消息段数组

    参数:
        message: 包含 CQ 码的字符串

    返回:
        消息段列表
    """
    segments: List[Dict[str, Any]] = []
    last_pos = 0

    for match in CQ_PATTERN.finditer(message):
        # 处理 CQ 码之前的文本
        text_part = message[last_pos : match.start()]
        if text_part:
            segments.append({"type": "text", "data": {"text": text_part}})

        # 处理 CQ 码及其子参数
        cq_type = match.group(1)
        cq_args_str = match.group(2)
        data: Dict[str, str] = {}

        if cq_args_str:
            for arg_pair in cq_args_str.split(","):
                if "=" in arg_pair:
                    k, v = arg_pair.split("=", 1)
                    data[k.strip()] = v.strip()

        segments.append({"type": cq_type, "data": data})
        last_pos = match.end()

    # 处理剩余的文本
    remaining_text = message[last_pos:]
    if remaining_text:
        segments.append({"type": "text", "data": {"text": remaining_text}})

    return segments


def matches_xinliweiyuan(text: str) -> bool:
    """判断文本是否匹配心理委员触发规则

    规则:
    1. 包含“心理委员”
    2. “心理委员”的前后（不同时存在）添加的部分统计非标点字符数 <= 5
    """
    keyword = "心理委员"
    if keyword not in text:
        return False

    def count_real_chars(s: str) -> int:
        """从字符串中移除标点和空格后的实际字符长度"""
        return len(PUNC_PATTERN.sub("", s))

    # 使用 split 分割出所有可能的上下文
    parts = text.split(keyword)

    # 遍历所有可能的“关键词”实例位置
    for i in range(len(parts) - 1):
        prefix = keyword.join(parts[: i + 1])
        suffix = keyword.join(parts[i + 1 :])

        prefix_count = count_real_chars(prefix)
        suffix_count = count_real_chars(suffix)

        # 同时仅1：不能前后都有字（标点不计）
        if prefix_count > 0 and suffix_count > 0:
            continue

        # 字数限制：添加的部分总字数 <= 5
        if (prefix_count + suffix_count) <= 5:
            return True

    return False
