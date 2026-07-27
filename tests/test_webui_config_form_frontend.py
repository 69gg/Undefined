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
RESPONSIVE_CSS: Final[Path] = Path("src/Undefined/webui/static/css/responsive.css")
UI_JS: Final[Path] = Path("src/Undefined/webui/static/js/ui.js")


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


def test_model_pool_entry_defaults_enable_thinking_parameter() -> None:
    source = _read_source(CONFIG_FORM_JS)
    defaults = source.split("const MODEL_POOL_ENTRY_DEFAULTS = {", 1)[1].split("};", 1)[
        0
    ]

    assert "thinking_param_enabled: true" in defaults


def _css_rule(source: str, selector: str) -> str:
    marker = f"{selector} {{"
    start = source.index(marker) + len(marker)
    return source[start : source.index("}", start)]


def test_config_form_uses_stable_single_column_layout() -> None:
    css = _read_source(COMPONENTS_CSS)
    responsive = _read_source(RESPONSIVE_CSS)

    form_rule = _css_rule(css, ".form-grid")
    assert "display: grid" in form_rule
    assert "grid-template-columns: minmax(0, 1fr)" in form_rule
    assert "column-width" not in form_rule
    assert "column-count" not in responsive

    card_rule = _css_rule(css, ".config-card")
    assert "inline-block" not in card_rule
    assert "break-inside" not in card_rule
    assert "margin-bottom: 0" in card_rule

    header_rule = _css_rule(css, ".config-card-header")
    assert "position: sticky" in header_rule
    assert "top: var(--config-section-sticky-offset)" in header_rule
    assert "minmax(260px, 1fr)" in css


def test_config_state_does_not_override_grid_display() -> None:
    source = _read_source(UI_JS)
    state_fn = source.split("function setConfigState(mode)", 1)[1].split(
        "function ", 1
    )[0]

    assert 'grid.style.display = "block"' not in state_fn
    assert 'grid.style.display = ""' in state_fn


def test_config_search_temporarily_expands_without_changing_saved_state() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is required for config section behavior test")

    source = _read_source(CONFIG_FORM_JS)
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(0, "utf8");

class TokenList {
  constructor(initial = []) { this.values = new Set(initial); }
  contains(value) { return this.values.has(value); }
  toggle(value, force) {
    if (force) this.values.add(value);
    else this.values.delete(value);
  }
}

function createButton() {
  return {
    attributes: {},
    title: "",
    setAttribute(name, value) { this.attributes[name] = String(value); },
    removeAttribute(name) { delete this.attributes[name]; },
  };
}

const label = { innerText: "" };
const toggle = createButton();
toggle.querySelector = (selector) =>
  selector === ".config-section-toggle-label" ? label : null;

const card = {
  dataset: { section: "models" },
  classList: new TokenList(["config-card"]),
  querySelector(selector) {
    return selector === ".config-section-toggle" ? toggle : null;
  },
};
const expandAll = createButton();
const collapseAll = createButton();
const state = {
  configSearch: "model",
  configCollapsed: { models: true },
  configSearchCollapsed: {},
  configSearchModeActive: false,
};
const context = {
  state,
  document: {
    querySelectorAll(selector) {
      return selector === ".config-card" ? [card] : [];
    },
  },
  get(id) {
    if (id === "btnExpandAll") return expandAll;
    if (id === "btnCollapseAll") return collapseAll;
    return null;
  },
  t(key) {
    const values = {
      "config.expand_section": "Expand",
      "config.collapse_section": "Collapse",
    };
    return values[key] || key;
  },
  window: {},
  console,
  setTimeout,
  clearTimeout,
};
vm.runInNewContext(source, context);

context.syncConfigSearchMode(true);
context.updateConfigSectionPresentations();
if (state.configCollapsed.models !== true) {
  throw new Error("search must not mutate saved collapse state");
}
if (card.classList.contains("is-collapsed")) {
  throw new Error("matching collapsed section must be temporarily expanded");
}
if (toggle.attributes["aria-expanded"] !== "true") {
  throw new Error("temporary expansion must update aria-expanded");
}
context.toggleSection("models");
if (!card.classList.contains("is-collapsed")) {
  throw new Error("section toggle must keep working during search");
}
if (state.configCollapsed.models !== true) {
  throw new Error("search toggle must not mutate saved collapse state");
}

state.configSearch = "";
context.syncConfigSearchMode(false);
context.updateConfigSectionPresentations();
if (!card.classList.contains("is-collapsed")) {
  throw new Error("clearing search must restore saved collapse state");
}
if (toggle.attributes["aria-expanded"] !== "false") {
  throw new Error("restored collapse state must update aria-expanded");
}
if (label.innerText !== "Expand") {
  throw new Error("restored collapsed section must use expand label");
}

console.log(JSON.stringify({ ok: true }));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        input=source,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, (
        "config section behavior test failed:\n"
        f"stdout={completed.stdout}\nstderr={completed.stderr}"
    )
    assert json.loads(completed.stdout.strip().splitlines()[-1])["ok"] is True


def test_config_collapse_preserves_the_visible_section_anchor() -> None:
    source = _read_source(CONFIG_FORM_JS)

    assert "function preserveConfigViewportAnchor(anchor, update)" in source
    assert "function findConfigViewportAnchor()" in source
    assert 'window.scrollBy({ top: delta, left: 0, behavior: "auto" })' in source
    assert "preserveConfigViewportAnchor(anchor" in source


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


def test_model_transport_controls_use_canonical_modes_and_replay_defaults() -> None:
    source = _read_source(CONFIG_FORM_JS)

    assert '"openai.chat_completions"' in source
    assert '"openai.responses"' in source
    assert '"anthropic.messages"' in source
    assert "reasoning_effort_style" not in source
    assert "reasoning_content_replay: true" in source
    assert "thinking_include_budget: true" in source
    assert "stream_enabled: false" in source


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
