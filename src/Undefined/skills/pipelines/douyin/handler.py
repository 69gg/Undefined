from __future__ import annotations

from typing import Any

from Undefined.skills.pipelines.models import PipelineContext, PipelineDetection


def _is_allowed(config: Any, target_type: str, target_id: int) -> bool:
    if not getattr(config, "douyin_auto_extract_enabled", False):
        return False
    if target_type == "group":
        return bool(config.is_douyin_auto_extract_allowed_group(target_id))
    return bool(config.is_douyin_auto_extract_allowed_private(target_id))


async def detect(context: PipelineContext) -> PipelineDetection | None:
    target_id = int(context["target_id"])
    target_type = str(context["target_type"])
    config = context["config"]
    if not _is_allowed(config, target_type, target_id):
        return None

    extractor = context["extract_douyin_ids"]
    video_ids = extractor(context["text"], context["message_content"])
    if not video_ids:
        return None
    return PipelineDetection(
        name="douyin", items=tuple(str(item) for item in video_ids)
    )


async def process(
    detection: PipelineDetection,
    context: PipelineContext,
) -> None:
    handler = context["handle_douyin_extract"]
    await handler(
        int(context["target_id"]),
        list(detection.items),
        str(context["target_type"]),
    )
