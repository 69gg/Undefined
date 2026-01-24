"""通用工具函数"""

import re
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


def extract_text(message_content: list[dict[str, Any]], bot_qq: int = 0) -> str:
    """提取消息中的文本内容

    参数:
        message_content: 消息内容列表
        bot_qq: 机器人 QQ 号（用于过滤 @ 机器人的内容），默认为 0（不过滤）

    返回:
        提取的文本
    """
    texts: list[str] = []
    for segment in message_content:
        type_ = segment.get("type", "")
        data = segment.get("data", {})

        if type_ == "text":
            texts.append(data.get("text", ""))
        elif type_ == "at":
            qq = data.get("qq", "")
            # 如果指定了 bot_qq 且 @ 的是 bot，则不显示 @
            if bot_qq and str(qq) == str(bot_qq):
                continue
            texts.append(f"[@ {qq}]")
        elif type_ == "image":
            file = data.get("file", "") or data.get("url", "")
            texts.append(f"[图片: {file}]")
        elif type_ == "file":
            file = data.get("file", "") or data.get("url", "")
            texts.append(f"[文件: {file}]")
        elif type_ == "video":
            file = data.get("file", "") or data.get("url", "")
            texts.append(f"[视频: {file}]")
        elif type_ == "record":
            file = data.get("file", "") or data.get("url", "")
            texts.append(f"[语音: {file}]")
        elif type_ == "audio":
            file = data.get("file", "") or data.get("url", "")
            texts.append(f"[音频: {file}]")

    return "".join(texts).strip()


async def parse_message_content_for_history(
    message_content: list[dict[str, Any]],
    bot_qq: int,
    get_msg_func: Callable[[int], Awaitable[dict[str, Any] | None]] | None = None,
) -> str:
    """解析消息内容用于历史记录（支持回复引用和 @ 格式化）

    参数:
        message_content: 消息内容列表
        bot_qq: 机器人 QQ 号
        get_msg_func: 获取消息详情的异步函数（可选，用于处理回复引用）

    返回:
        解析后的文本
    """
    texts: list[str] = []
    for segment in message_content:
        type_ = segment.get("type")
        data = segment.get("data", {})

        if type_ == "text":
            texts.append(data.get("text", ""))

        elif type_ == "at":
            qq = data.get("qq", "")
            # 仅当 @ 的不是机器人时才显示，且使用指定格式
            if str(qq) != str(bot_qq):
                texts.append(f"[@ {qq}]")

        elif type_ == "image":
            file = data.get("file", "") or data.get("url", "")
            texts.append(f"[图片: {file}]")

        elif type_ == "file":
            file = data.get("file", "") or data.get("url", "")
            texts.append(f"[文件: {file}]")

        elif type_ == "video":
            file = data.get("file", "") or data.get("url", "")
            texts.append(f"[视频: {file}]")

        elif type_ == "record":
            file = data.get("file", "") or data.get("url", "")
            texts.append(f"[语音: {file}]")

        elif type_ == "audio":
            file = data.get("file", "") or data.get("url", "")
            texts.append(f"[音频: {file}]")

        elif type_ == "forward":
            msg_id = data.get("id")
            if msg_id:
                # 合并转发只保存简单标记，AI 可以通过 get_forward_msg 工具查看完整内容
                texts.append(f"[合并转发: {msg_id}]")

        elif type_ == "reply":
            msg_id = data.get("id")
            if msg_id and get_msg_func:
                try:
                    # 尝试获取引用的消息内容
                    reply_msg = await get_msg_func(int(msg_id))
                    if reply_msg:
                        sender = reply_msg.get("sender", {}).get("nickname", "未知")
                        content = reply_msg.get("message", [])
                        # 使用 extract_text 解析引用内容
                        quote_text = extract_text(content, bot_qq)
                        texts.append(f'<quote sender="{sender}">{quote_text}</quote>\n')
                except Exception as e:
                    logger.warning(f"获取回复消息失败: {e}")

        elif type_ == "face":
            texts.append("[表情]")

    return "".join(texts).strip()


def message_to_segments(message: str) -> list[dict[str, Any]]:
    """将包含 CQ 码的字符串转换为 OneBot 消息段数组

    参数:
        message: 包含 CQ 码的字符串

    返回:
        消息段列表
    """
    segments = []
    # 匹配 CQ 码的正则
    # [CQ:type,arg1=val1,arg2=val2]
    cq_pattern = re.compile(r"\[CQ:([a-zA-Z0-9_-]+),?([^\]]*)\]")

    last_pos = 0
    for match in cq_pattern.finditer(message):
        # 处理 CQ 码之前的文本
        text_part = message[last_pos : match.start()]
        if text_part:
            segments.append({"type": "text", "data": {"text": text_part}})

        # 处理 CQ 码
        cq_type = match.group(1)
        cq_args_str = match.group(2)

        # 解析参数
        data = {}
        if cq_args_str:
            for arg_pair in cq_args_str.split(","):
                if "=" in arg_pair:
                    k, v = arg_pair.split("=", 1)
                    # 注意：这里假设输入的 CQ 码已经是经过 OneBot 转义的格式
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
    1. 单独“心理委员” (可选加标点/空格)
    2. 前后（同时仅1）添加 5 个字以内（标点/空格不计入字数）
    """
    keyword = "心理委员"
    if keyword not in text:
        return False

    # 分割文本，找到关键字的位置
    parts = text.split(keyword)
    # 如果出现多次关键词，只要其中一个位置满足条件即可触发
    # 但为了简单和符合直觉，我们检查是否【任何】一种分割方式满足条件
    # 通常文本里只会有一个“心理委员”用于触发

    # 标点符号和空白字符正则
    # \s 匹配空白，[^\w\s] 在大多数情况下匹配标点（但在 Python 3 中 \w 包含中文）
    # 我们直接定义非“字”的模式：空白、常见标点
    punc_pattern = r'[ \t\n\r\f\v\s!"#$%&\'()*+,\-./:;<=>?@\[\\\]^_`{|}~，。！？、；：""\'\'（）【】「」《》—…·]'

    def count_real_chars(s: str) -> int:
        """移除标点和空格后的长度"""
        return len(re.sub(punc_pattern, "", s))

    # 遍历所有可能的分割（以防文本中有多个“心理委员”）
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
