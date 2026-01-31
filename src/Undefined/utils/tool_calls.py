"""Tool call helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _clean_json_string(raw: str) -> str:
    """Remove control characters that commonly break JSON parsing."""
    return raw.replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()


def parse_tool_arguments(
    raw_args: Any,
    *,
    logger: logging.Logger | None = None,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Parse tool call arguments into a dict.

    Accepts dict, JSON string, or empty/None. Returns an empty dict for
    unsupported or invalid inputs.
    """
    if isinstance(raw_args, dict):
        return raw_args

    if raw_args is None:
        return {}

    if isinstance(raw_args, str):
        if not raw_args.strip():
            return {}
        cleaned = raw_args
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            cleaned = _clean_json_string(raw_args)
            if cleaned != raw_args:
                try:
                    parsed = json.loads(cleaned)
                    if logger:
                        logger.warning(
                            "[工具警告] 参数包含控制字符，已清理: tool=%s",
                            tool_name or "unknown",
                        )
                    return parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    pass
            try:
                parsed, _ = json.JSONDecoder().raw_decode(cleaned)
                if logger:
                    logger.warning(
                        "[工具警告] 参数包含尾部内容，已截断: tool=%s",
                        tool_name or "unknown",
                    )
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                if logger:
                    logger.error(
                        "[工具错误] 参数解析失败: %s, 错误: %s",
                        raw_args,
                        exc,
                    )
                return {}
        if isinstance(parsed, dict):
            return parsed
        if logger:
            logger.warning(
                "[工具警告] 参数解析结果非对象: tool=%s type=%s",
                tool_name or "unknown",
                type(parsed).__name__,
            )
        return {}

    if logger:
        logger.warning(
            "[工具警告] 参数类型不支持: tool=%s type=%s",
            tool_name or "unknown",
            type(raw_args).__name__,
        )
    return {}
