from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from Undefined.skills.auto_pipeline import AutoPipelineRegistry


def _write_pipeline(base_dir: Path) -> None:
    item_dir = base_dir / "example"
    item_dir.mkdir(parents=True)
    (item_dir / "config.json").write_text(
        """
{
    "name": "example",
    "description": "测试管线",
    "order": 10,
    "enabled": true
}
""".strip(),
        encoding="utf-8",
    )
    (item_dir / "handler.py").write_text(
        """
from __future__ import annotations

from Undefined.skills.auto_pipeline.models import AutoPipelineDetection


async def detect(context):
    context["events"].append("detect")
    return AutoPipelineDetection(name="example", items=("item",))


async def process(detection, context):
    context["events"].append(f"process:{detection.items[0]}")
""".strip(),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_auto_pipeline_registry_loads_and_runs_configured_pipeline(
    tmp_path: Path,
) -> None:
    _write_pipeline(tmp_path)
    registry = AutoPipelineRegistry(tmp_path)
    registry.load_items()
    context: dict[str, Any] = {"events": []}

    detections = await registry.run(context)

    assert [detection.name for detection in detections] == ["example"]
    assert context["events"] == ["detect", "process:item"]
