from __future__ import annotations

from typing import Any

from Undefined.skills.pipelines.models import (
    PipelineContext,
    PipelineDetection,
)


def _is_allowed(config: Any, target_type: str, target_id: int) -> bool:
    # 图文复用视频的白名单与总开关，只额外受 opus_enabled 控制
    if not getattr(config, "bilibili_auto_extract_enabled", False):
        return False
    if not getattr(config, "bilibili_opus_enabled", True):
        return False
    if target_type == "group":
        return bool(config.is_bilibili_auto_extract_allowed_group(target_id))
    return bool(config.is_bilibili_auto_extract_allowed_private(target_id))


async def detect(context: PipelineContext) -> PipelineDetection | None:
    target_id = int(context["target_id"])
    target_type = str(context["target_type"])
    config = context["config"]
    if not _is_allowed(config, target_type, target_id):
        return None

    extractor = context["extract_bilibili_opus_ids"]
    opus_ids = await extractor(context["text"], context["message_content"])
    if not opus_ids:
        return None
    return PipelineDetection(
        name="bilibili_opus", items=tuple(str(item) for item in opus_ids)
    )


async def process(
    detection: PipelineDetection,
    context: PipelineContext,
) -> None:
    handler = context["handle_bilibili_opus_extract"]
    args = (
        int(context["target_id"]),
        list(detection.items),
        str(context["target_type"]),
    )
    if context.get("address") is None:
        await handler(*args)
    else:
        await handler(*args, context["sender"])
