"""Static + behavioral frontend contracts for WebUI config form (request_params / search)."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

from Undefined.utils import io as async_io

CONFIG_FORM_JS: Final[Path] = Path("src/Undefined/webui/static/js/config-form.js")
COMPONENTS_CSS: Final[Path] = Path("src/Undefined/webui/static/css/components.css")


def _read_source(path: Path) -> str:
    text = asyncio.run(async_io.read_text(path))
    assert text is not None
    return text


def _has_bare_form_group_query(source: str) -> bool:
    """True if source still queries all .form-group nodes (not only [data-path])."""
    return (
        'querySelectorAll(".form-group")' in source
        or '".form-group:not(.is-hidden)"' in source
    )


def test_config_search_filters_only_path_bearing_form_groups() -> None:
    """Nested key/type form-groups inside request_params must not be filtered alone."""
    source = _read_source(CONFIG_FORM_JS)

    assert 'querySelectorAll(".form-group[data-path]")' in source
    assert ".form-group[data-path]:not(.is-hidden)" in source
    assert not _has_bare_form_group_query(source)


def test_config_search_index_only_targets_path_bearing_form_groups() -> None:
    source = _read_source(CONFIG_FORM_JS)
    index_fn = source.split("function updateConfigSearchIndex()", 1)[1].split(
        "function ", 1
    )[0]
    assert 'querySelectorAll(".form-group[data-path]")' in index_fn
    assert 'querySelectorAll(".form-group")' not in index_fn


def test_apply_config_filter_only_targets_path_bearing_form_groups() -> None:
    source = _read_source(CONFIG_FORM_JS)
    filter_fn = source.split("function applyConfigFilter()", 1)[1].split(
        "function ", 1
    )[0]
    assert 'querySelectorAll(".form-group[data-path]")' in filter_fn
    assert ".form-group[data-path]:not(.is-hidden)" in filter_fn
    assert 'querySelectorAll(".form-group")' not in filter_fn
    assert '".form-group:not(.is-hidden)"' not in filter_fn


def test_request_params_widget_contracts() -> None:
    source = _read_source(CONFIG_FORM_JS)
    css = _read_source(COMPONENTS_CSS)

    assert "function isRequestParamsPath(path)" in source
    assert 'path.endsWith(".request_params")' in source
    assert "function createRequestParamsWidget(path, value)" in source
    assert 'editor.dataset.requestParamsRoot = "true"' in source
    assert "config-request-params" in source
    assert ".form-group.config-request-params" in css
    assert "grid-column: 1 / -1" in css


def test_request_params_nested_key_type_editors_lack_data_path() -> None:
    """key/type structural editors must not get data-path (or search will hide them)."""
    source = _read_source(CONFIG_FORM_JS)

    key_entry = source.split("function createStructuredObjectEntry", 1)[1].split(
        "function ", 1
    )[0]
    assert 'keyGroup.className = "form-group"' in key_entry
    assert "keyGroup.dataset.path" not in key_entry
    assert "keyGroup.dataset.searchText" not in key_entry

    scalar = source.split("function createStructuredScalarEditor", 1)[1].split(
        "function ", 1
    )[0]
    assert 'typeGroup.className = "form-group"' in scalar
    assert "typeGroup.dataset.path" not in scalar
    assert "typeGroup.dataset.searchText" not in scalar

    widget = source.split("function createRequestParamsWidget", 1)[1].split(
        "function ", 1
    )[0]
    assert "group.dataset.path = path" in widget


def test_apply_config_filter_behavior_keeps_nested_request_params_visible() -> None:
    """Mini-DOM behavioral check: parent match keeps nested key/type form-groups visible.

    Replicates applyConfigFilter's selection rule (only .form-group[data-path])
    against a request_params-shaped tree without pulling in jsdom.
    """
    if shutil.which("node") is None:
        pytest.skip("node is required for mini-DOM config filter behavior test")

    script = r"""
class TokenList {
  constructor(el) { this.el = el; this._set = new Set(); }
  add(c) { this._set.add(c); }
  remove(c) { this._set.delete(c); }
  contains(c) { return this._set.has(c); }
  toggle(c, force) {
    if (force === undefined) {
      if (this._set.has(c)) { this._set.delete(c); return false; }
      this._set.add(c); return true;
    }
    if (force) { this._set.add(c); return true; }
    this._set.delete(c); return false;
  }
  toArray() { return [...this._set]; }
}

function matchesSelector(el, selector) {
  if (selector === ".config-card") {
    return el.classList.contains("config-card");
  }
  if (selector === ".form-subsection") {
    return el.classList.contains("form-subsection");
  }
  if (selector === ".form-group[data-path]") {
    return el.classList.contains("form-group") && el.dataset.path != null && el.dataset.path !== "";
  }
  if (selector === ".form-group[data-path]:not(.is-hidden)") {
    return (
      el.classList.contains("form-group") &&
      el.dataset.path != null &&
      el.dataset.path !== "" &&
      !el.classList.contains("is-hidden")
    );
  }
  return false;
}

function walk(root, selector, out) {
  if (matchesSelector(root, selector)) out.push(root);
  for (const child of root.children || []) walk(child, selector, out);
  return out;
}

function createEl(tag, className, dataset = {}) {
  const el = {
    tagName: tag.toUpperCase(),
    classList: null,
    dataset: { ...dataset },
    children: [],
    parent: null,
    style: {},
    querySelectorAll(sel) {
      const out = [];
      for (const child of this.children) walk(child, sel, out);
      return out;
    },
    querySelector(sel) {
      return this.querySelectorAll(sel)[0] || null;
    },
  };
  el.classList = new TokenList(el);
  // bridge TokenList <-> string className for contains checks
  const originalAdd = el.classList.add.bind(el.classList);
  const originalRemove = el.classList.remove.bind(el.classList);
  const originalToggle = el.classList.toggle.bind(el.classList);
  el.classList.add = (...args) => {
    for (const c of args) {
      originalAdd(c);
      el._className = (el._className || "") + " " + c;
    }
  };
  el.classList.remove = (...args) => {
    for (const c of args) {
      originalRemove(c);
    }
  };
  el.classList.toggle = (c, force) => {
    const result = originalToggle(c, force);
    return result;
  };
  el.classList.contains = (c) => el.classList._set.has(c);
  if (className) {
    for (const c of className.split(/\s+/).filter(Boolean)) el.classList.add(c);
  }
  return el;
}

function append(parent, child) {
  child.parent = parent;
  parent.children.push(child);
  return child;
}

// Build: card > parent request_params form-group[data-path] > nested key/type form-groups
const card = createEl("div", "config-card");
const parent = createEl("div", "form-group config-request-params", {
  path: "models.image_gen.request_params",
  searchText: "models.image_gen.request_params response_format",
});
const keyGroup = createEl("div", "form-group"); // no data-path
const typeGroup = createEl("div", "form-group"); // no data-path
append(parent, keyGroup);
append(parent, typeGroup);
append(card, parent);

const other = createEl("div", "form-group", {
  path: "models.image_gen.api_url",
  searchText: "models.image_gen.api_url api url",
});
append(card, other);

const document = {
  querySelectorAll(sel) {
    if (sel === ".config-card") return [card];
    return [];
  },
};

// Mirror applyConfigFilter selection rules from config-form.js
function applyConfigFilter(query) {
  document.querySelectorAll(".config-card").forEach((cardEl) => {
    let cardMatches = 0;
    cardEl.querySelectorAll(".form-group[data-path]").forEach((group) => {
      const isMatch = !query || (group.dataset.searchText || "").includes(query);
      group.classList.toggle("is-hidden", !isMatch);
      group.classList.toggle("is-match", isMatch && query.length > 0);
      if (isMatch) cardMatches += 1;
    });
    cardEl.classList.toggle("is-hidden", query.length > 0 && cardMatches === 0);
  });
}

applyConfigFilter("request_params");

const result = {
  parentHidden: parent.classList.contains("is-hidden"),
  parentMatch: parent.classList.contains("is-match"),
  keyHidden: keyGroup.classList.contains("is-hidden"),
  typeHidden: typeGroup.classList.contains("is-hidden"),
  otherHidden: other.classList.contains("is-hidden"),
  pathBearingCount: card.querySelectorAll(".form-group[data-path]").length,
  allFormGroupCount: (() => {
    const out = [];
    function countAll(el) {
      if (el.classList && el.classList.contains("form-group")) out.push(el);
      for (const c of el.children || []) countAll(c);
    }
    countAll(card);
    return out.length;
  })(),
};

if (result.parentHidden) throw new Error("parent request_params should be visible on match");
if (!result.parentMatch) throw new Error("parent should be marked is-match");
if (result.keyHidden) throw new Error("nested key form-group must not be auto-hidden");
if (result.typeHidden) throw new Error("nested type form-group must not be auto-hidden");
if (!result.otherHidden) throw new Error("non-matching field should be hidden");
if (result.pathBearingCount !== 2) throw new Error("expected 2 path-bearing form-groups");
if (result.allFormGroupCount !== 4) throw new Error("expected 4 total form-groups in tree");

// Empty query shows everything
applyConfigFilter("");
if (parent.classList.contains("is-hidden")) throw new Error("empty query: parent hidden");
if (other.classList.contains("is-hidden")) throw new Error("empty query: other hidden");
if (keyGroup.classList.contains("is-hidden")) throw new Error("empty query: key hidden");

console.log(JSON.stringify({ ok: true, ...result }));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, (
        f"mini-DOM filter test failed:\nstdout={completed.stdout}\nstderr={completed.stderr}"
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["keyHidden"] is False
    assert payload["typeHidden"] is False
    assert payload["parentHidden"] is False
    assert payload["otherHidden"] is True
