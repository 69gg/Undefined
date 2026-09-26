"""Frontend contracts for the automations list / canvas pages."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Final

from Undefined.utils import io as async_io

SCHEDULES_JS: Final[Path] = Path("src/Undefined/webui/static/js/schedules.js")
GRAPH_JS: Final[Path] = Path("src/Undefined/webui/static/js/workflow-graph.js")
INSPECTOR_JS: Final[Path] = Path("src/Undefined/webui/static/js/workflow-inspector.js")
I18N_JS: Final[Path] = Path("src/Undefined/webui/static/js/i18n.js")
CREATE_TOOL_CONFIG: Final[Path] = Path(
    "src/Undefined/skills/toolsets/automation/create/config.json"
)


def _read_source(path: Path) -> str:
    text = asyncio.run(async_io.read_text(path))
    assert text is not None
    return text


def test_save_reloads_list_and_scrolls_to_list_page() -> None:
    source = _read_source(SCHEDULES_JS)
    save_fn = source.split("async function save()", 1)[1].split(
        "async function removeSelected()", 1
    )[0]
    refresh_fn = source.split("async function refresh(options = {})", 1)[1].split(
        "function maybeOpenFromQuery()", 1
    )[0]

    assert "if (scheduleState.busy && !force) return;" in refresh_fn
    assert "await refresh({ force: true, skipOpenFromQuery: true });" in save_fn
    assert 'showSchedulePage("list")' in save_fn


def test_workflow_payload_preserves_nulls_and_omits_legacy_address_target() -> None:
    graph = _read_source(GRAPH_JS)
    payload = graph.split("payload()", 1)[1].split("window.WorkflowGraph", 1)[0]

    assert 'Object.hasOwn(copy, "max_executions")' in payload
    assert 'Object.hasOwn(copy, "cooldown_seconds")' in payload
    assert 'Object.hasOwn(copy, "address")' in payload
    assert 'Object.hasOwn(copy, "target_id")' in payload
    assert 'Object.hasOwn(copy, "target_type")' in payload
    assert "next.target_id = targetId" in payload
    assert "next.target_type = targetType" in payload


def test_automation_create_schema_exposes_at_and_interval_requirements() -> None:
    config = json.loads(_read_source(CREATE_TOOL_CONFIG))
    parameters = config["function"]["parameters"]

    assert parameters["properties"]["at"]["type"] == "string"
    assert parameters["properties"]["interval_seconds"] == {
        "type": "integer",
        "minimum": 1,
        "description": "固定间隔秒数，kind=interval 时必填",
    }
    required_by_kind = {
        item["if"]["properties"]["kind"]["const"]: item["then"]["required"]
        for item in parameters["allOf"]
    }
    assert required_by_kind == {"at": ["at"], "interval": ["interval_seconds"]}
