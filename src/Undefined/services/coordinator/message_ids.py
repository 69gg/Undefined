from __future__ import annotations

from Undefined.services.message_batcher import BufferedMessage


def collect_message_ids(items: list[BufferedMessage]) -> list[str]:
    """Collect all known message IDs from a grouped request."""
    message_ids: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item.trigger_message_id is None:
            continue
        message_id = str(item.trigger_message_id).strip()
        if not message_id or message_id in seen:
            continue
        seen.add(message_id)
        message_ids.append(message_id)
    return message_ids
