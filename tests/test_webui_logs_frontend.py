"""Behavioral contracts for record-level WebUI log filtering."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

from Undefined.utils import io as async_io


LOGS_JS: Final[Path] = Path("src/Undefined/webui/static/js/logs.js")
LOG_VIEW_JS: Final[Path] = Path("src/Undefined/webui/static/js/log-view.js")


def _read_source(path: Path) -> str:
    text = asyncio.run(async_io.read_text(path))
    assert text is not None
    return text


def test_log_filters_match_and_return_complete_multiline_records() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is required for WebUI log filtering behavior test")

    sources = json.dumps(
        {
            "logs": _read_source(LOGS_JS),
            "view": _read_source(LOG_VIEW_JS),
        }
    )
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const sources = JSON.parse(fs.readFileSync(0, "utf8"));
const context = {
  window: {},
  state: {
    logSearch: "",
    logLevel: "all",
    logLevelGte: false,
    logTimeFrom: "",
    logTimeTo: "",
  },
  console,
};
vm.runInNewContext(sources.logs, context);
vm.runInNewContext(sources.view, context);

const raw = [
  "2026-07-11 22:32:45,941 [INFO] [2126af26] Undefined.skills.registry: [agent调用] web_agent 参数={",
  '  "prompt": "查询当前（2026年7月11日附近）火星到地球的距离，并给出大致光程时间。"',
  "}",
  "2026-07-11 22:32:46.100 [ERROR] [deadbeef] Undefined.worker: 调用失败",
  "Traceback (most recent call last):",
  '  File "worker.py", line 1, in run',
  "ValueError: upstream failed",
  "2026-07-11 22:32:47,000 [DEBUG] [feedface] Undefined.worker: cleanup complete",
].join("\n");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const controller = context.window.LogsController;
const records = controller.parseLogRecords(raw);
assert(records.length === 3, `expected 3 records, got ${records.length}`);
assert(records[0].lines.length === 3, "INFO JSON record must contain all 3 lines");
assert(records[1].lines.length === 4, "ERROR traceback record must contain all 4 lines");

context.state.logSearch = "火星";
let result = context.filterLogLines(raw);
assert(result.total === 3, `total must count records, got ${result.total}`);
assert(result.matched === 1, `expected one matching record, got ${result.matched}`);
assert(result.filtered.length === 3, "query match must return the complete JSON record");
assert(result.filtered[0].includes("[agent调用]"), "record header must be retained");
assert(result.filtered[1].includes("火星到地球"), "matching continuation line missing");
assert(result.filtered[2] === "}", "record closing line must be retained");
assert(!result.filtered.join("\n").includes("调用失败"), "next record must be excluded");

context.state.logSearch = "UPSTREAM FAILED";
context.state.logLevel = "error";
result = context.filterLogLines(raw);
assert(result.matched === 1, "case-insensitive traceback query must match error record");
assert(result.filtered.length === 4, "traceback match must return its complete record");
assert(result.filtered[0].includes("[ERROR]"), "error record header must be retained");
assert(result.filtered[1].startsWith("Traceback"), "traceback body must be retained");

context.state.logSearch = "火星";
result = context.filterLogLines(raw);
assert(result.matched === 0, "record must also satisfy the selected log level");

context.state.logSearch = "upstream failed";
context.state.logLevel = "info";
context.state.logLevelGte = true;
result = context.filterLogLines(raw);
assert(result.matched === 1, "level-at-or-above must operate on the whole record");

const firstTimestamp = controller.parseLogTimestamp(records[0].lines[0]);
context.state.logSearch = "";
context.state.logLevel = "all";
context.state.logLevelGte = false;
context.state.logTimeFrom = new Date(firstTimestamp - 1).toISOString();
context.state.logTimeTo = new Date(firstTimestamp + 1).toISOString();
result = context.filterLogLines(raw);
assert(result.matched === 1, "time range must match by record start timestamp");
assert(result.filtered.length === 3, "time filtering must retain the complete record");

const partialRaw = [
  '  "prompt": "tail fragment"',
  "}",
  "2026-07-11 22:32:47,000 [INFO] Undefined.worker: next record",
].join("\n");
const partial = controller.filterLogLines(partialRaw, { query: "tail fragment" });
assert(partial.total === 2, "leading tail fragment must remain a separate record");
assert(partial.matched === 1, "leading tail fragment must remain searchable");
assert(partial.filtered.length === 2, "all available fragment lines must be returned");

const isoRange = controller.filterLogLines(raw, {
  timeFrom: new Date(firstTimestamp - 1).toISOString(),
  timeTo: new Date(firstTimestamp + 1).toISOString(),
});
assert(isoRange.matched === 1, "record filter must accept ISO timestamp strings");

const numericRange = controller.filterLogLines(raw, {
  timeFrom: firstTimestamp - 1,
  timeTo: firstTimestamp + 1,
});
assert(numericRange.matched === 1, "record filter must preserve numeric timestamps");

const invalidRange = controller.filterLogLines(raw, {
  timeFrom: "not-a-date",
  timeTo: "still-not-a-date",
});
assert(invalidRange.matched === 3, "invalid timestamps must not activate a filter");

console.log(JSON.stringify({ ok: true, total: records.length }));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        input=sources,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, (
        "WebUI log filtering behavior test failed:\n"
        f"stdout={completed.stdout}\nstderr={completed.stderr}"
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload == {"ok": True, "total": 3}


def test_log_view_delegates_all_filters_to_record_parser() -> None:
    source = _read_source(LOG_VIEW_JS)
    filter_fn = source.split("function filterLogLines(raw)", 1)[1].split(
        "function ", 1
    )[0]

    assert "window.LogsController.filterLogLines(raw" in filter_fn
    assert "level: state.logLevel" in filter_fn
    assert "gte: state.logLevelGte" in filter_fn
    assert "query," in filter_fn
    assert "timeFrom:" in filter_fn
    assert "timeTo:" in filter_fn
    assert "const LOG_TAIL_LINES = 5000;" in source
