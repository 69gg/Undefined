"""WebUI for config editing."""

from __future__ import annotations

import asyncio
import difflib
import logging
import secrets
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from Undefined.config import WebUISettings, load_webui_settings
from Undefined.config.loader import CONFIG_PATH, Config, load_toml_data

logger = logging.getLogger(__name__)

CONFIG_EXAMPLE_PATH = Path("config.toml.example")
SESSION_COOKIE = "undefined_webui"
SESSION_TTL_SECONDS = 8 * 60 * 60
MAX_LOG_LINES = 500
DEFAULT_LOG_LINES = 200

TomlData = dict[str, Any]

SECTION_ORDER: dict[str, list[str]] = {
    "": [
        "core",
        "onebot",
        "models",
        "logging",
        "tools",
        "skills",
        "search",
        "proxy",
        "weather",
        "xxapi",
        "token_usage",
        "mcp",
        "webui",
    ],
    "models": ["chat", "vision", "security", "agent"],
}

KEY_ORDER: dict[str, list[str]] = {
    "core": ["bot_qq", "superadmin_qq", "admin_qq", "forward_proxy_qq"],
    "onebot": ["ws_url", "token"],
    "logging": ["level", "file_path", "max_size_mb", "backup_count", "log_thinking"],
    "tools": [
        "sanitize",
        "description_max_len",
        "sanitize_verbose",
        "description_preview_len",
    ],
    "skills": [
        "hot_reload",
        "hot_reload_interval",
        "hot_reload_debounce",
        "intro_autogen_enabled",
        "intro_autogen_queue_interval",
        "intro_autogen_max_tokens",
        "intro_hash_path",
        "prefetch_tools",
        "prefetch_tools_hide",
    ],
    "search": ["searxng_url"],
    "proxy": ["use_proxy", "http_proxy", "https_proxy"],
    "weather": ["api_key"],
    "xxapi": ["api_token"],
    "token_usage": [
        "max_size_mb",
        "max_archives",
        "max_total_mb",
        "archive_prune_mode",
    ],
    "mcp": ["config_path"],
    "webui": ["url", "port", "password"],
    "models.chat": [
        "api_url",
        "api_key",
        "model_name",
        "max_tokens",
        "thinking_enabled",
        "thinking_budget_tokens",
        "deepseek_new_cot_support",
    ],
    "models.vision": [
        "api_url",
        "api_key",
        "model_name",
        "thinking_enabled",
        "thinking_budget_tokens",
        "deepseek_new_cot_support",
    ],
    "models.security": [
        "api_url",
        "api_key",
        "model_name",
        "max_tokens",
        "thinking_enabled",
        "thinking_budget_tokens",
        "deepseek_new_cot_support",
    ],
    "models.agent": [
        "api_url",
        "api_key",
        "model_name",
        "max_tokens",
        "thinking_enabled",
        "thinking_budget_tokens",
        "deepseek_new_cot_support",
    ],
}


@dataclass
class ConfigSource:
    content: str
    exists: bool
    source: str


class SessionStore:
    def __init__(self, ttl_seconds: int = SESSION_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, float] = {}

    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = time.time() + self._ttl_seconds
        return token

    def is_valid(self, token: str | None) -> bool:
        if not token:
            return False
        expiry = self._sessions.get(token)
        if not expiry:
            return False
        if expiry < time.time():
            self._sessions.pop(token, None)
            return False
        return True

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        self._sessions.pop(token, None)


def _read_config_source() -> ConfigSource:
    if CONFIG_PATH.exists():
        return ConfigSource(
            content=CONFIG_PATH.read_text(encoding="utf-8"),
            exists=True,
            source=str(CONFIG_PATH),
        )
    if CONFIG_EXAMPLE_PATH.exists():
        return ConfigSource(
            content=CONFIG_EXAMPLE_PATH.read_text(encoding="utf-8"),
            exists=False,
            source=str(CONFIG_EXAMPLE_PATH),
        )
    return ConfigSource(
        content="[core]\nbot_qq = 0\nsuperadmin_qq = 0\n",
        exists=False,
        source="inline",
    )


def _validate_toml(content: str) -> tuple[bool, str]:
    try:
        tomllib.loads(content)
        return True, "OK"
    except tomllib.TOMLDecodeError as exc:
        return False, f"TOML parse error: {exc}"


def _validate_required_config() -> tuple[bool, str]:
    try:
        Config.load(strict=True)
        return True, "OK"
    except Exception as exc:
        return False, str(exc)


def _load_default_data() -> TomlData:
    if not CONFIG_EXAMPLE_PATH.exists():
        return {}
    try:
        with open(CONFIG_EXAMPLE_PATH, "rb") as f:
            data = tomllib.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def _merge_defaults(defaults: TomlData, data: TomlData) -> TomlData:
    merged: TomlData = dict(defaults)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_defaults(merged[key], value)
        else:
            merged[key] = value
    return merged


def _sorted_keys(table: TomlData, path: list[str]) -> list[str]:
    path_key = ".".join(path) if path else ""
    order = KEY_ORDER.get(path_key) or SECTION_ORDER.get(path_key)
    if not order:
        return sorted(table.keys())
    order_index = {name: idx for idx, name in enumerate(order)}
    return sorted(
        table.keys(),
        key=lambda name: (order_index.get(name, 999), name),
    )


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        items = ", ".join(_format_value(item) for item in value)
        return f"[{items}]"
    return f'"{str(value)}"'


def _render_table(path: list[str], table: TomlData) -> list[str]:
    lines: list[str] = []
    items: list[str] = []
    for key in _sorted_keys(table, path):
        value = table[key]
        if isinstance(value, dict):
            continue
        items.append(f"{key} = {_format_value(value)}")
    if items and path:
        lines.append(f"[{'.'.join(path)}]")
        lines.extend(items)
        lines.append("")
    elif items and not path:
        lines.extend(items)
        lines.append("")

    for key in _sorted_keys(table, path):
        value = table[key]
        if not isinstance(value, dict):
            continue
        lines.extend(_render_table(path + [key], value))
    return lines


def _render_toml(data: TomlData) -> str:
    if not data:
        return ""
    lines = _render_table([], data)
    content = "\n".join(lines).rstrip() + "\n"
    return content


def _apply_patch(data: TomlData, patch: dict[str, Any]) -> TomlData:
    for path, value in patch.items():
        if not path:
            continue
        parts = path.split(".")
        node = data
        for key in parts[:-1]:
            if key not in node or not isinstance(node[key], dict):
                node[key] = {}
            node = node[key]
        node[parts[-1]] = value
    return data


def _tail_file(path: Path, lines: int) -> str:
    if lines <= 0:
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
            block_size = 4096
            data = bytearray()
            remaining = file_size
            while remaining > 0 and data.count(b"\n") <= lines:
                read_size = min(block_size, remaining)
                f.seek(remaining - read_size)
                chunk = f.read(read_size)
                data[:0] = chunk
                remaining -= read_size
            text = data.decode("utf-8", errors="replace")
            return "\n".join(text.splitlines()[-lines:])
    except Exception as exc:
        return f"Failed to read logs: {exc}"


def _render_page(initial_view: str, using_default_password: bool) -> str:
    default_flag = "true" if using_default_password else "false"
    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Undefined Config Console</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Serif:wght@400;500;600&display=swap');
    :root {
      --bg: #f6f1e8;
      --bg-deep: #efe6d8;
      --ink: #1f1b16;
      --muted: #6d6256;
      --accent: #c78b2f;
      --accent-dark: #8c5e1d;
      --green: #2f6b4f;
      --surface: #fff8ee;
      --stroke: #e3d7c8;
      --shadow: 0 24px 60px rgba(31, 27, 22, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Noto Sans SC", sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at 10% 10%, #fff7ec 0%, var(--bg) 45%, var(--bg-deep) 100%);
      min-height: 100vh;
    }
    a { color: inherit; text-decoration: none; }
    .noise {
      position: fixed;
      inset: 0;
      background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200"><filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" stitchTiles="stitch"/></filter><rect width="200" height="200" filter="url(%23n)" opacity="0.05"/></svg>');
      pointer-events: none;
      mix-blend-mode: multiply;
      opacity: 0.15;
    }
    .shell { display: grid; grid-template-rows: auto 1fr; min-height: 100vh; }
    header {
      padding: 28px 60px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .brand {
      font-family: "IBM Plex Serif", serif;
      font-size: 22px;
      letter-spacing: 0.5px;
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .brand .dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 0 6px rgba(199, 139, 47, 0.15);
    }
    .header-actions { display: flex; gap: 12px; font-size: 14px; color: var(--muted); }
    .pill { border: 1px solid var(--stroke); border-radius: 999px; padding: 6px 14px; background: rgba(255, 248, 238, 0.8); }
    main { padding: 0 60px 60px; }
    .card { background: var(--surface); border: 1px solid var(--stroke); border-radius: 24px; padding: 28px; box-shadow: var(--shadow); }
    .hero { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 28px; align-items: center; }
    .hero h1 { font-family: "IBM Plex Serif", serif; font-size: 42px; margin: 0 0 12px; }
    .hero p { margin: 0; color: var(--muted); line-height: 1.6; }
    .cta {
      display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 12px 20px;
      border-radius: 999px; border: none; background: var(--accent); color: #1f1408; font-weight: 600; cursor: pointer;
      transition: transform 0.2s ease, box-shadow 0.2s ease; box-shadow: 0 12px 24px rgba(199, 139, 47, 0.25);
    }
    .cta:hover { transform: translateY(-1px); }
    .section { margin-top: 28px; display: none; }
    .section.active { display: block; animation: fadeUp 0.4s ease; }
    @keyframes fadeUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
    .grid { display: grid; grid-template-columns: 1.4fr 0.6fr; gap: 24px; }
    .panel { background: #fffdf7; border: 1px solid var(--stroke); border-radius: 20px; padding: 18px; }
    .panel h3 { margin: 0 0 12px; font-size: 16px; }
    .panel-stack { display: grid; gap: 16px; }
    .panel-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
    .panel-row-controls { display: flex; align-items: center; gap: 8px; }
    .panel-row-controls select {
      padding: 6px 8px; border-radius: 8px; border: 1px solid var(--stroke); background: #fff; font-size: 12px;
    }
    .toggle { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
    .toggle input { margin: 0; accent-color: var(--accent); }
    .editor {
      width: 100%; min-height: 420px; border-radius: 14px; border: 1px solid var(--stroke); padding: 16px;
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace; font-size: 13px; line-height: 1.6;
      background: #fdf7ef; color: #2d241c; resize: vertical;
    }
    .toolbar { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0; }
    .btn { padding: 10px 16px; border-radius: 999px; border: 1px solid var(--stroke); background: #fff; cursor: pointer; font-weight: 600; }
    .btn.primary { background: var(--accent); color: #1f1408; border-color: transparent; }
    .btn.ghost { background: transparent; }
    .status { margin-top: 10px; font-size: 13px; color: var(--muted); }
    .badge { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; font-size: 12px; background: rgba(47, 107, 79, 0.12); color: var(--green); border: 1px solid rgba(47, 107, 79, 0.2); }
    .warning {
      display: flex; gap: 10px; align-items: flex-start; border: 1px solid rgba(199, 139, 47, 0.4);
      background: rgba(199, 139, 47, 0.12); color: #7a4e14; padding: 12px 14px; border-radius: 14px; font-size: 13px;
    }
    .login { display: grid; gap: 12px; }
    .login input { padding: 10px 12px; border-radius: 10px; border: 1px solid var(--stroke); background: #fff; }
    .muted { color: var(--muted); font-size: 13px; line-height: 1.6; }
    .field-grid { display: grid; gap: 10px; }
    .field { display: grid; gap: 6px; }
    .field label { font-size: 12px; color: var(--muted); }
    .field input, .field select {
      padding: 8px 10px; border-radius: 10px; border: 1px solid var(--stroke); background: #fff; font-size: 13px;
    }
    .mono-block {
      background: #f7efe5; border: 1px solid var(--stroke); border-radius: 12px; padding: 12px;
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace; font-size: 12px; white-space: pre-wrap;
      max-height: 240px; overflow: auto;
    }
    footer { margin-top: 32px; color: var(--muted); font-size: 12px; }
    @media (max-width: 980px) { header, main { padding: 24px; } .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="noise"></div>
  <div class="shell">
    <header>
      <div class="brand"><span class="dot"></span>Undefined Console</div>
      <div class="header-actions">
        <span class="pill">config.toml</span>
        <span class="pill">WebUI</span>
      </div>
    </header>
    <main>
      <section id="landing" class="section">
        <div class="card hero">
          <div>
            <h1>Config Command Center</h1>
            <p>Warm, focused tooling for tuning your runtime setup. Use the console to edit, validate, and keep your configuration sharp.</p>
          </div>
          <div>
            <p class="muted">WebUI starts with a secure passphrase. Update it after first boot to keep control tight.</p>
            <div style="margin-top:16px;">
              <a href="/app" class="cta">Open Console</a>
            </div>
          </div>
        </div>
      </section>

      <section id="app" class="section">
        <div class="grid">
          <div class="card">
            <div id="warningBox" class="warning" style="display:none;">
              <div>Default password is active. Change <strong>webui.password</strong> and restart WebUI.</div>
            </div>
            <div id="loginBox" class="login">
              <h2>Unlock Console</h2>
              <input id="passwordInput" type="password" placeholder="WebUI password" />
              <button id="loginBtn" class="btn primary">Sign in</button>
              <div class="status" id="loginStatus"></div>
            </div>

            <div id="editorBox" style="display:none;">
              <h2>config.toml</h2>
              <textarea id="configEditor" class="editor" spellcheck="false"></textarea>
              <div class="toolbar">
                <button id="saveBtn" class="btn primary">Save</button>
                <button id="refreshBtn" class="btn ghost">Reload</button>
                <button id="validateBtn" class="btn ghost">Validate</button>
                <button id="diffBtn" class="btn ghost">Diff</button>
                <button id="logoutBtn" class="btn ghost">Sign out</button>
              </div>
              <div class="status" id="saveStatus"></div>
            </div>
          </div>

          <div class="panel-stack">
            <div class="panel">
              <h3>Status</h3>
              <div class="status" id="statusBlock">Connecting...</div>
              <div style="margin:16px 0;" class="badge">Hot reload via bot process</div>
              <p class="muted">WebUI reads config on startup. If you change WebUI settings, restart this process.</p>
            </div>

            <div class="panel" id="formPanel" style="display:none;">
              <div class="panel-row">
                <h3>Quick Edit</h3>
                <button id="applyFormBtn" class="btn primary">Apply</button>
              </div>
              <div id="formSections" class="field-grid"></div>
            </div>

            <div class="panel" id="diffPanel" style="display:none;">
              <div class="panel-row">
                <h3>Diff Preview</h3>
                <button id="refreshDiffBtn" class="btn ghost">Refresh</button>
              </div>
              <div id="diffPreview" class="mono-block">No diff yet.</div>
            </div>

            <div class="panel" id="logPanel" style="display:none;">
              <div class="panel-row">
                <h3>Log Tail</h3>
                <div class="panel-row-controls">
                  <label class="toggle">
                    <input id="autoLogToggle" type="checkbox" checked />
                    Auto refresh
                  </label>
                  <select id="logInterval">
                    <option value="3000">3s</option>
                    <option value="5000" selected>5s</option>
                    <option value="10000">10s</option>
                    <option value="30000">30s</option>
                  </select>
                  <button id="refreshLogsBtn" class="btn ghost">Refresh</button>
                </div>
              </div>
              <div id="logPreview" class="mono-block">Logs will appear here.</div>
            </div>
          </div>
        </div>
        <footer>Warm console for precise config edits.</footer>
      </section>
    </main>
  </div>
  <script>
    const initialView = "__INITIAL_VIEW__";
    const usingDefaultPassword = __DEFAULT_FLAG__;
    const landing = document.getElementById('landing');
    const app = document.getElementById('app');
    const warningBox = document.getElementById('warningBox');
    const loginBox = document.getElementById('loginBox');
    const editorBox = document.getElementById('editorBox');
    const loginBtn = document.getElementById('loginBtn');
    const logoutBtn = document.getElementById('logoutBtn');
    const saveBtn = document.getElementById('saveBtn');
    const refreshBtn = document.getElementById('refreshBtn');
    const validateBtn = document.getElementById('validateBtn');
    const diffBtn = document.getElementById('diffBtn');
    const refreshDiffBtn = document.getElementById('refreshDiffBtn');
    const refreshLogsBtn = document.getElementById('refreshLogsBtn');
    const autoLogToggle = document.getElementById('autoLogToggle');
    const logInterval = document.getElementById('logInterval');
    const applyFormBtn = document.getElementById('applyFormBtn');
    const passwordInput = document.getElementById('passwordInput');
    const configEditor = document.getElementById('configEditor');
    const loginStatus = document.getElementById('loginStatus');
    const saveStatus = document.getElementById('saveStatus');
    const statusBlock = document.getElementById('statusBlock');
    const diffPreview = document.getElementById('diffPreview');
    const logPreview = document.getElementById('logPreview');
    const formPanel = document.getElementById('formPanel');
    const diffPanel = document.getElementById('diffPanel');
    const logPanel = document.getElementById('logPanel');
    const formSections = document.getElementById('formSections');
    let logTimer = null;

    const FORM_DEFINITION = [
      {
        title: 'Core',
        fields: [
          { path: 'core.bot_qq', label: 'Bot QQ', type: 'number' },
          { path: 'core.superadmin_qq', label: 'Superadmin QQ', type: 'number' },
          { path: 'core.admin_qq', label: 'Admin QQs (comma)', type: 'list-int' },
        ]
      },
      {
        title: 'OneBot',
        fields: [
          { path: 'onebot.ws_url', label: 'WebSocket URL', type: 'string' },
          { path: 'onebot.token', label: 'Token', type: 'string' }
        ]
      },
      {
        title: 'WebUI',
        fields: [
          { path: 'webui.url', label: 'URL', type: 'string' },
          { path: 'webui.port', label: 'Port', type: 'number' },
          { path: 'webui.password', label: 'Password', type: 'string' }
        ]
      },
      {
        title: 'Logging',
        fields: [
          { path: 'logging.level', label: 'Level', type: 'string' },
          { path: 'logging.log_thinking', label: 'Log Thinking', type: 'bool' }
        ]
      },
      {
        title: 'Skills',
        fields: [
          { path: 'skills.hot_reload', label: 'Hot Reload', type: 'bool' },
          { path: 'skills.hot_reload_interval', label: 'Reload Interval', type: 'number' },
          { path: 'skills.hot_reload_debounce', label: 'Reload Debounce', type: 'number' }
        ]
      },
      {
        title: 'Token Usage',
        fields: [
          { path: 'token_usage.max_size_mb', label: 'Max Size MB', type: 'number' },
          { path: 'token_usage.max_archives', label: 'Max Archives', type: 'number' },
          { path: 'token_usage.archive_prune_mode', label: 'Prune Mode', type: 'string' }
        ]
      }
    ];

    let formState = {};

    function showSection(view) {
      landing.classList.toggle('active', view === 'landing');
      app.classList.toggle('active', view === 'app');
    }

    async function api(path, options = {}) {
      const res = await fetch(path, options);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || data.message || 'Request failed');
      }
      return data;
    }

    function getValueByPath(obj, path) {
      const parts = path.split('.');
      let node = obj;
      for (const part of parts) {
        if (!node || typeof node !== 'object' || !(part in node)) {
          return null;
        }
        node = node[part];
      }
      return node;
    }

    function normalizeFormValue(value, type) {
      if (type === 'bool') {
        return value === true || value === 'true';
      }
      if (type === 'number') {
        const num = Number(value);
        return Number.isFinite(num) ? num : null;
      }
      if (type === 'list-int') {
        if (!value) {
          return [];
        }
        return value.split(',').map(item => parseInt(item.trim(), 10)).filter(n => Number.isFinite(n));
      }
      return value ?? '';
    }

    function renderForm(summary) {
      formSections.innerHTML = '';
      formState = {};
      FORM_DEFINITION.forEach(section => {
        const sectionWrap = document.createElement('div');
        sectionWrap.className = 'panel';
        const title = document.createElement('h3');
        title.textContent = section.title;
        sectionWrap.appendChild(title);
        const fieldsWrap = document.createElement('div');
        fieldsWrap.className = 'field-grid';
        section.fields.forEach(field => {
          const fieldWrap = document.createElement('div');
          fieldWrap.className = 'field';
          const label = document.createElement('label');
          label.textContent = field.label;
          let input;
          if (field.type === 'bool') {
            input = document.createElement('select');
            ['true', 'false'].forEach(value => {
              const option = document.createElement('option');
              option.value = value;
              option.textContent = value;
              input.appendChild(option);
            });
          } else {
            input = document.createElement('input');
            if (field.type === 'number') {
              input.type = 'number';
            } else {
              input.type = 'text';
            }
          }
          const value = getValueByPath(summary, field.path);
          const normalized = normalizeFormValue(value, field.type);
          if (field.type === 'list-int') {
            input.value = Array.isArray(normalized) ? normalized.join(', ') : '';
          } else if (field.type === 'bool') {
            input.value = normalized ? 'true' : 'false';
          } else if (normalized !== null && normalized !== undefined) {
            input.value = normalized;
          }
          formState[field.path] = normalized;
          input.dataset.path = field.path;
          input.dataset.type = field.type;
          fieldWrap.appendChild(label);
          fieldWrap.appendChild(input);
          fieldsWrap.appendChild(fieldWrap);
        });
        sectionWrap.appendChild(fieldsWrap);
        formSections.appendChild(sectionWrap);
      });
    }

    function stopLogAutoRefresh() {
      if (logTimer) {
        clearInterval(logTimer);
        logTimer = null;
      }
    }

    function startLogAutoRefresh() {
      stopLogAutoRefresh();
      if (!autoLogToggle || !autoLogToggle.checked) {
        return;
      }
      const interval = Number(logInterval?.value) || 5000;
      logTimer = setInterval(() => {
        loadLogs();
      }, interval);
    }

    async function checkSession() {
      const data = await api('/api/session');
      warningBox.style.display = data.using_default_password ? 'flex' : 'none';
      statusBlock.textContent = data.summary;
      if (data.authenticated) {
        loginBox.style.display = 'none';
        editorBox.style.display = 'block';
        formPanel.style.display = 'block';
        diffPanel.style.display = 'block';
        logPanel.style.display = 'block';
        await loadConfig();
        await loadSummary();
        await loadLogs();
        startLogAutoRefresh();
      } else {
        loginBox.style.display = 'grid';
        editorBox.style.display = 'none';
        formPanel.style.display = 'none';
        diffPanel.style.display = 'none';
        logPanel.style.display = 'none';
        stopLogAutoRefresh();
      }
    }

    async function loadConfig() {
      const data = await api('/api/config');
      configEditor.value = data.content || '';
      saveStatus.textContent = `Loaded from ${data.source}`;
    }

    async function loadSummary() {
      const data = await api('/api/config/summary');
      renderForm(data.data || {});
    }

    async function loadDiff() {
      const data = await api('/api/diff', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: configEditor.value })
      });
      diffPreview.textContent = data.diff || 'No diff.';
    }

    async function loadLogs() {
      const data = await api('/api/logs');
      logPreview.textContent = data.content || '';
    }

    async function saveConfig() {
      saveStatus.textContent = 'Saving...';
      try {
        const data = await api('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: configEditor.value })
        });
        saveStatus.textContent = data.message;
      } catch (err) {
        saveStatus.textContent = err.message;
      }
    }

    async function applyForm() {
      const patch = {};
      formSections.querySelectorAll('[data-path]').forEach(input => {
        const path = input.dataset.path;
        const type = input.dataset.type;
        let value = input.value;
        const normalized = normalizeFormValue(value, type);
        const original = formState[path];
        if (JSON.stringify(normalized) !== JSON.stringify(original)) {
          patch[path] = normalized;
        }
      });
      if (Object.keys(patch).length === 0) {
        saveStatus.textContent = 'No form changes to apply.';
        return;
      }
      saveStatus.textContent = 'Applying form...';
      try {
        const data = await api('/api/patch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: configEditor.value, patch })
        });
        configEditor.value = data.content || '';
        await loadSummary();
        saveStatus.textContent = 'Form changes applied.';
      } catch (err) {
        saveStatus.textContent = err.message;
      }
    }

    async function validateConfig() {
      saveStatus.textContent = 'Validating...';
      try {
        const data = await api('/api/validate');
        saveStatus.textContent = data.message;
      } catch (err) {
        saveStatus.textContent = err.message;
      }
    }

    loginBtn?.addEventListener('click', async () => {
      loginStatus.textContent = 'Checking...';
      try {
        await api('/api/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: passwordInput.value })
        });
        loginStatus.textContent = 'Signed in.';
        await checkSession();
      } catch (err) {
        loginStatus.textContent = err.message;
      }
    });

    logoutBtn?.addEventListener('click', async () => {
      try {
        await api('/api/logout', { method: 'POST' });
      } finally {
        await checkSession();
      }
    });

    saveBtn?.addEventListener('click', saveConfig);
    refreshBtn?.addEventListener('click', loadConfig);
    validateBtn?.addEventListener('click', validateConfig);
    diffBtn?.addEventListener('click', loadDiff);
    refreshDiffBtn?.addEventListener('click', loadDiff);
    refreshLogsBtn?.addEventListener('click', loadLogs);
    autoLogToggle?.addEventListener('change', startLogAutoRefresh);
    logInterval?.addEventListener('change', startLogAutoRefresh);
    applyFormBtn?.addEventListener('click', applyForm);

    if (initialView === 'landing') {
      showSection('landing');
    } else {
      showSection('app');
      checkSession();
    }
  </script>
</body>
</html>"""
    return template.replace("__INITIAL_VIEW__", initial_view).replace(
        "__DEFAULT_FLAG__", default_flag
    )


async def _handle_index(request: web.Request) -> web.Response:
    settings: WebUISettings = request.app["settings"]
    html = _render_page("landing", settings.using_default_password)
    return web.Response(text=html, content_type="text/html")


async def _handle_app(request: web.Request) -> web.Response:
    settings: WebUISettings = request.app["settings"]
    html = _render_page("app", settings.using_default_password)
    return web.Response(text=html, content_type="text/html")


def _is_authenticated(request: web.Request) -> bool:
    sessions: SessionStore = request.app["sessions"]
    token = request.cookies.get(SESSION_COOKIE)
    return sessions.is_valid(token)


async def _handle_session(request: web.Request) -> web.Response:
    settings: WebUISettings = request.app["settings"]
    authenticated = _is_authenticated(request)
    summary = (
        f"{settings.url}:{settings.port} | {'ready' if authenticated else 'locked'}"
    )
    payload = {
        "authenticated": authenticated,
        "using_default_password": settings.using_default_password,
        "config_exists": settings.config_exists,
        "config_path": str(CONFIG_PATH),
        "summary": summary,
    }
    return web.json_response(payload)


async def _handle_login(request: web.Request) -> web.Response:
    settings: WebUISettings = request.app["settings"]
    sessions: SessionStore = request.app["sessions"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    password = str(body.get("password", ""))
    if password != settings.password:
        return web.json_response({"error": "Invalid password"}, status=401)
    token = sessions.create()
    response = web.json_response({"ok": True})
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="Lax")
    return response


async def _handle_logout(request: web.Request) -> web.Response:
    sessions: SessionStore = request.app["sessions"]
    token = request.cookies.get(SESSION_COOKIE)
    sessions.revoke(token)
    response = web.json_response({"ok": True})
    response.del_cookie(SESSION_COOKIE)
    return response


async def _handle_config_get(request: web.Request) -> web.Response:
    if not _is_authenticated(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    source = _read_config_source()
    return web.json_response(
        {
            "content": source.content,
            "exists": source.exists,
            "source": source.source,
        }
    )


async def _handle_config_post(request: web.Request) -> web.Response:
    if not _is_authenticated(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    content = body.get("content")
    if not isinstance(content, str):
        return web.json_response({"error": "Missing content"}, status=400)
    ok, message = _validate_toml(content)
    if not ok:
        return web.json_response({"error": message}, status=400)
    CONFIG_PATH.write_text(content, encoding="utf-8")
    validation_ok, validation_msg = _validate_required_config()
    if validation_ok:
        result_message = "Saved. Config looks good."
    else:
        result_message = f"Saved. Warning: {validation_msg}"
    return web.json_response({"ok": True, "message": result_message})


async def _handle_validate(request: web.Request) -> web.Response:
    if not _is_authenticated(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    ok, message = _validate_required_config()
    status = 200 if ok else 400
    return web.json_response({"ok": ok, "message": message}, status=status)


async def _handle_summary(request: web.Request) -> web.Response:
    if not _is_authenticated(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    data = load_toml_data()
    defaults = _load_default_data()
    summary = _merge_defaults(defaults, data)
    return web.json_response({"data": summary})


async def _handle_patch(request: web.Request) -> web.Response:
    if not _is_authenticated(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    content = body.get("content")
    patch = body.get("patch")
    if not isinstance(content, str) or not isinstance(patch, dict):
        return web.json_response({"error": "Invalid payload"}, status=400)
    try:
        data = tomllib.loads(content) if content.strip() else {}
    except tomllib.TOMLDecodeError as exc:
        return web.json_response({"error": f"TOML parse error: {exc}"}, status=400)
    if not isinstance(data, dict):
        data = {}
    patched = _apply_patch(data, patch)
    rendered = _render_toml(patched)
    return web.json_response({"content": rendered})


async def _handle_diff(request: web.Request) -> web.Response:
    if not _is_authenticated(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    content = body.get("content")
    if not isinstance(content, str):
        return web.json_response({"error": "Missing content"}, status=400)
    source = _read_config_source()
    original_lines = source.content.splitlines()
    new_lines = content.splitlines()
    diff_lines = list(
        difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=source.source,
            tofile=str(CONFIG_PATH),
            lineterm="",
        )
    )
    diff_text = "\n".join(diff_lines) if diff_lines else "No diff."
    return web.json_response({"diff": diff_text})


async def _handle_logs(request: web.Request) -> web.Response:
    if not _is_authenticated(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        raw_lines = request.query.get("lines", str(DEFAULT_LOG_LINES))
        lines = min(int(raw_lines), MAX_LOG_LINES)
    except ValueError:
        lines = DEFAULT_LOG_LINES
    try:
        config = Config.load(strict=False)
        log_path = Path(config.log_file_path)
    except Exception:
        log_path = Path("logs/bot.log")
    if not log_path.exists():
        return web.json_response({"content": f"Log file not found: {log_path}"})
    content = _tail_file(log_path, lines)
    return web.json_response({"content": content})


def _create_app(settings: WebUISettings) -> web.Application:
    app = web.Application()
    app["settings"] = settings
    app["sessions"] = SessionStore()
    app.add_routes(
        [
            web.get("/", _handle_index),
            web.get("/app", _handle_app),
            web.get("/api/session", _handle_session),
            web.post("/api/login", _handle_login),
            web.post("/api/logout", _handle_logout),
            web.get("/api/config", _handle_config_get),
            web.post("/api/config", _handle_config_post),
            web.get("/api/validate", _handle_validate),
            web.get("/api/config/summary", _handle_summary),
            web.post("/api/patch", _handle_patch),
            web.post("/api/diff", _handle_diff),
            web.get("/api/logs", _handle_logs),
        ]
    )
    return app


async def _run_webui() -> None:
    settings = load_webui_settings()
    if settings.using_default_password:
        logger.warning(
            "WebUI password missing; using default: %s (update webui.password soon)",
            settings.password,
        )
    logger.info("WebUI listening on http://%s:%s", settings.url, settings.port)
    app = _create_app(settings)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.url, settings.port)
    await site.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(_run_webui())


if __name__ == "__main__":
    run()
