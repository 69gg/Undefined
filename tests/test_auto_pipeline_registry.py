from __future__ import annotations

import asyncio
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


@pytest.mark.asyncio
async def test_auto_pipeline_registry_initial_async_load_uses_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AutoPipelineRegistry(tmp_path)
    calls: list[Any] = []

    async def _fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(registry, "_load_items_sync", lambda: {})

    await registry.load_items_async()

    assert calls == [registry._load_items_sync]
    assert registry._items == {}


@pytest.mark.asyncio
async def test_auto_pipeline_reload_loads_items_in_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AutoPipelineRegistry(tmp_path)
    calls: list[Any] = []

    async def _fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(registry, "_load_items_sync", lambda: {})

    await registry._reload_items()

    assert calls == [registry._load_items_sync]
    assert registry._items == {}
