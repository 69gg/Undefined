"""Prompt 构建相关常量与正则。"""

from __future__ import annotations

import re

from Undefined.utils.xml import XML_CONTENT_BODY_PATTERN

CURRENT_MESSAGE_RE = re.compile(
    rf"<message\b(?P<attrs>[^>]*)>.*?"
    rf"<content>(?P<content>{XML_CONTENT_BODY_PATTERN})</content>.*?</message>",
    re.DOTALL | re.IGNORECASE,
)
XML_ATTR_RE = re.compile(r'(?P<key>[a-zA-Z_][a-zA-Z0-9_-]*)="(?P<value>[^"]*)"')
COGNITIVE_QUERY_SHORT_THRESHOLD = 20  # 低于此长度视为短 query，追加语境
COGNITIVE_CONTEXT_VALUE_MAX_LEN = 18  # 注入检索 query 的单字段上限

__all__ = [
    "COGNITIVE_CONTEXT_VALUE_MAX_LEN",
    "COGNITIVE_QUERY_SHORT_THRESHOLD",
    "CURRENT_MESSAGE_RE",
    "XML_ATTR_RE",
]
