from __future__ import annotations

from typing import Any

from Undefined.skills.auto_pipeline.models import (
    AutoPipelineContext,
    AutoPipelineDetection,
)


def _is_allowed(config: Any, target_type: str, target_id: int) -> bool:
    if not getattr(config, "bilibili_auto_extract_enabled", False):
        return False
    if target_type == "group":
        return bool(config.is_bilibili_auto_extract_allowed_group(target_id))
    return bool(config.is_bilibili_auto_extract_allowed_private(target_id))


async def detect(context: AutoPipelineContext) -> AutoPipelineDetection | None:
    target_id = int(context["target_id"])
    target_type = str(context["target_type"])
    config = context["config"]
    if not _is_allowed(config, target_type, target_id):
        return None

    extractor = context["extract_bilibili_ids"]
    bvids = await extractor(context["text"], context["message_content"])
    if not bvids:
        return None
    return AutoPipelineDetection(
        name="bilibili", items=tuple(str(item) for item in bvids)
    )


async def process(
    detection: AutoPipelineDetection,
    context: AutoPipelineContext,
) -> None:
    handler = context["handle_bilibili_extract"]
    await handler(
        int(context["target_id"]),
        list(detection.items),
        str(context["target_type"]),
    )
