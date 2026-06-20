from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def mark_message_sent(context: dict[str, Any]) -> None:
    marker = context.get("mark_message_sent_this_turn")
    if not callable(marker):
        logger.warning("缺少 mark_message_sent_this_turn 上下文依赖")
        return
    marker(context)
