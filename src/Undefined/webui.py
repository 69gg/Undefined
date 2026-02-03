"""WebUI for config editing."""

from __future__ import annotations

import asyncio
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
TOKEN_COOKIE = "undefined_webui_token"
SESSION_TTL_SECONDS = 8 * 60 * 60
MAX_LOG_LINES = 500
DEFAULT_LOG_LINES = 200
BOT_COMMAND = ("uv", "run", "Undefined")

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


class BotProcessController:
    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._started_at: float | None = None
        self._lock = asyncio.Lock()
        self._watch_task: asyncio.Task[None] | None = None

    def status(self) -> dict[str, Any]:
        running = bool(self._process and self._process.returncode is None)
        uptime = 0.0
        if running and self._started_at:
            uptime = max(0.0, time.time() - self._started_at)
        return {
            "running": running,
            "pid": self._process.pid if running and self._process else None,
            "started_at": self._started_at,
            "uptime_seconds": uptime,
            "command": " ".join(BOT_COMMAND),
        }

    async def start(self) -> dict[str, Any]:
        async with self._lock:
            if self._process and self._process.returncode is None:
                return self.status()
            logger.info("[WebUI] 启动机器人进程: %s", " ".join(BOT_COMMAND))
            self._process = await asyncio.create_subprocess_exec(
                *BOT_COMMAND,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            self._started_at = time.time()
            self._watch_task = asyncio.create_task(self._watch_process(self._process))
            return self.status()

    async def stop(self) -> dict[str, Any]:
        async with self._lock:
            if not self._process or self._process.returncode is not None:
                self._process = None
                self._started_at = None
                return self.status()
            logger.info("[WebUI] 停止机器人进程: pid=%s", self._process.pid)
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.warning("[WebUI] 机器人进程未及时退出，强制终止")
                self._process.kill()
                await self._process.wait()
            self._process = None
            self._started_at = None
            return self.status()

    async def _watch_process(self, process: asyncio.subprocess.Process) -> None:
        await process.wait()
        async with self._lock:
            if self._process is process:
                self._process = None
                self._started_at = None


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
    return "\n".join(lines).rstrip() + "\n"


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
<html lang="zh-CN" data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Undefined Console</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Serif:wght@400;500;600&display=swap');
    :root {
      --bg: #f6f1e8;
      --bg-deep: #efe6d8;
      --bg-glow: #fff7ec;
      --ink: #1f1b16;
      --muted: #6d6256;
      --accent: #c78b2f;
      --accent-dark: #8c5e1d;
      --green: #2f6b4f;
      --surface: #fff8ee;
      --panel: #fffdf7;
      --stroke: #e3d7c8;
      --shadow: 0 24px 60px rgba(31, 27, 22, 0.12);
      --nav: #f2e4d3;
      --nav-ink: #2a2117;
      --field: #fff;
      --chip: #f7efe5;
    }
    [data-theme="dark"] {
      --bg: #0f1112;
      --bg-deep: #14181a;
      --bg-glow: #1b2125;
      --ink: #f4efe7;
      --muted: #b2a79b;
      --accent: #f0b45c;
      --accent-dark: #c8812b;
      --green: #78b692;
      --surface: #171c1f;
      --panel: #1d2327;
      --stroke: #2b3439;
      --shadow: 0 24px 60px rgba(0, 0, 0, 0.45);
      --nav: #161b1f;
      --nav-ink: #f4efe7;
      --field: #12171a;
      --chip: #20262b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Noto Sans SC", sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at 12% 12%, var(--bg-glow) 0%, var(--bg) 45%, var(--bg-deep) 100%);
      min-height: 100vh;
    }
    a { color: inherit; text-decoration: none; }
    button { font-family: inherit; }
    .noise {
      position: fixed;
      inset: 0;
      background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200"><filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" stitchTiles="stitch"/></filter><rect width="200" height="200" filter="url(%23n)" opacity="0.05"/></svg>');
      pointer-events: none;
      mix-blend-mode: multiply;
      opacity: 0.18;
    }
    .shell { display: grid; grid-template-rows: auto 1fr; min-height: 100vh; }
    header {
      padding: 26px 60px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
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
    .header-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .pill { border: 1px solid var(--stroke); border-radius: 999px; padding: 6px 14px; background: rgba(255, 248, 238, 0.7); font-size: 12px; }
    .icon-btn {
      border: 1px solid var(--stroke);
      background: var(--surface);
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 12px;
      cursor: pointer;
    }
    main { padding: 0 60px 60px; }
    .card { background: var(--surface); border: 1px solid var(--stroke); border-radius: 24px; padding: 28px; box-shadow: var(--shadow); }
    .hero { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 28px; align-items: center; }
    .eyebrow { font-size: 12px; text-transform: uppercase; letter-spacing: 2px; color: var(--muted); }
    .hero h1 { font-family: "IBM Plex Serif", serif; font-size: 42px; margin: 12px 0; }
    .hero p { margin: 0 0 12px; color: var(--muted); line-height: 1.6; }
    .tagline { font-size: 14px; color: var(--ink); }
    .cta-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 20px; }
    .section { margin-top: 28px; display: none; }
    .section.active { display: block; animation: fadeUp 0.4s ease; }
    @keyframes fadeUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
    .grid { display: grid; grid-template-columns: 1.4fr 0.8fr; gap: 24px; }
    .panel { background: var(--panel); border: 1px solid var(--stroke); border-radius: 20px; padding: 18px; }
    .panel h3 { margin: 0 0 12px; font-size: 16px; }
    .panel-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
    .panel-stack { display: grid; gap: 16px; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
    .btn { padding: 10px 16px; border-radius: 999px; border: 1px solid var(--stroke); background: var(--surface); cursor: pointer; font-weight: 600; }
    .btn.primary { background: var(--accent); color: #1f1408; border-color: transparent; }
    .btn.ghost { background: transparent; }
    .btn.small { padding: 6px 12px; font-size: 12px; }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .status { margin-top: 10px; font-size: 13px; color: var(--muted); }
    .badge { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; font-size: 12px; background: rgba(47, 107, 79, 0.12); color: var(--green); border: 1px solid rgba(47, 107, 79, 0.2); }
    .badge.warn { background: rgba(199, 139, 47, 0.12); color: var(--accent-dark); border-color: rgba(199, 139, 47, 0.2); }
    .warning {
      display: flex; gap: 10px; align-items: flex-start; border: 1px solid rgba(199, 139, 47, 0.4);
      background: rgba(199, 139, 47, 0.12); color: #7a4e14; padding: 12px 14px; border-radius: 14px; font-size: 13px;
    }
    .muted { color: var(--muted); font-size: 13px; line-height: 1.6; }
    .app-shell { display: grid; grid-template-columns: 200px 1fr; gap: 22px; }
    .sidebar {
      background: var(--nav);
      border: 1px solid var(--stroke);
      border-radius: 24px;
      padding: 16px;
      display: grid;
      gap: 12px;
      min-height: 480px;
    }
    .nav-title { font-size: 12px; text-transform: uppercase; letter-spacing: 2px; color: var(--muted); }
    .nav-item {
      display: flex; align-items: center; gap: 10px; width: 100%;
      padding: 10px 14px; border-radius: 14px; border: 1px solid transparent;
      background: transparent; color: var(--nav-ink); cursor: pointer; font-weight: 600;
    }
    .nav-item.active { background: rgba(255, 255, 255, 0.5); border-color: var(--stroke); }
    [data-theme="dark"] .nav-item.active { background: rgba(255, 255, 255, 0.08); }
    .nav-footer { margin-top: auto; font-size: 12px; color: var(--muted); }
    .login { display: grid; gap: 12px; }
    .login input { padding: 10px 12px; border-radius: 10px; border: 1px solid var(--stroke); background: var(--field); color: var(--ink); }
    .tab { display: none; }
    .tab.active { display: block; animation: fadeUp 0.4s ease; }
    .field-grid { display: grid; gap: 12px; }
    .field { display: grid; gap: 6px; }
    .field label { font-size: 12px; color: var(--muted); }
    .field input, .field select {
      padding: 8px 10px; border-radius: 10px; border: 1px solid var(--stroke); background: var(--field); color: var(--ink); font-size: 13px;
    }
    .section-title { font-size: 16px; margin: 0 0 12px; }
    .form-section { margin-bottom: 18px; }
    .mono-block {
      background: var(--chip); border: 1px solid var(--stroke); border-radius: 12px; padding: 12px;
      font-family: "IBM Plex Mono", "SFMono-Regular", monospace; font-size: 12px; white-space: pre-wrap; max-height: 420px; overflow: auto; color: var(--ink);
    }
    .panel-row-controls { display: flex; align-items: center; gap: 8px; }
    .panel-row-controls select { padding: 6px 8px; border-radius: 8px; border: 1px solid var(--stroke); background: var(--field); font-size: 12px; color: var(--ink); }
    .toggle { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
    .toggle input { margin: 0; accent-color: var(--accent); }
    .link-grid { display: grid; gap: 10px; }
    .link-card {
      padding: 12px 14px; border-radius: 14px; border: 1px solid var(--stroke); background: var(--surface);
      display: flex; align-items: center; justify-content: space-between; font-weight: 600;
    }
    footer { margin-top: 32px; color: var(--muted); font-size: 12px; }
    @media (max-width: 1100px) {
      header, main { padding: 24px; }
      .grid { grid-template-columns: 1fr; }
      .app-shell { grid-template-columns: 1fr; }
      .sidebar { min-height: auto; }
    }
  </style>
</head>
<body>
  <div class="noise"></div>
  <div class="shell">
    <header>
      <div class="brand"><span class="dot"></span><span id="brandTitle">Undefined Console</span></div>
      <div class="header-actions">
        <span class="pill" id="statusPill">config.toml</span>
        <button class="icon-btn" id="themeToggle">Light</button>
        <button class="icon-btn" id="langToggle">中文</button>
        <button class="btn ghost small" id="logoutBtn" style="display:none;" data-i18n="auth.sign_out">Sign out</button>
      </div>
    </header>
    <main>
      <section id="landing" class="section">
        <div class="card hero">
          <div>
            <div class="eyebrow" data-i18n="landing.kicker">WebUI</div>
            <h1 data-i18n="landing.title">配置控制台</h1>
            <p class="tagline">A high-performance, highly scalable QQ group and private chat robot based on a self-developed architecture.</p>
            <p class="muted" data-i18n="landing.subtitle">提供配置管理、日志追踪与运行控制的统一入口。</p>
            <div class="cta-row">
              <button class="btn primary" data-action="open-app" data-tab="config" data-i18n="landing.cta">进入控制台</button>
              <button class="btn ghost" data-action="open-app" data-tab="logs" data-i18n="landing.logs">日志查看</button>
              <button class="btn ghost" data-action="open-app" data-tab="about" data-i18n="landing.about">作者与版权</button>
            </div>
          </div>
          <div class="panel-stack">
            <div class="panel">
              <div class="panel-row">
                <h3 data-i18n="bot.title">Bot 控制</h3>
                <span id="botStateBadge" class="badge">--</span>
              </div>
              <div class="status" id="botStatus">--</div>
              <div class="toolbar">
                <button id="botStartBtn" class="btn primary" data-i18n="bot.start">启动</button>
                <button id="botStopBtn" class="btn ghost" data-i18n="bot.stop">停止</button>
              </div>
              <div class="muted" id="botHint">--</div>
            </div>
            <div class="panel" id="landingLoginBox" style="display:none;">
              <div class="panel-row">
                <h3 data-i18n="auth.title">解锁控制台</h3>
                <span class="badge warn" data-i18n="bot.locked">已锁定</span>
              </div>
              <div class="field" style="margin-bottom:10px;">
                <label data-i18n="auth.placeholder">WebUI 密码</label>
                <input id="landingPasswordInput" type="password" data-i18n-placeholder="auth.placeholder" placeholder="WebUI password" />
              </div>
              <button id="landingLoginBtn" class="btn primary" data-i18n="auth.sign_in">登录</button>
              <div class="status" id="landingLoginStatus"></div>
            </div>
            <div class="panel">
              <h3 data-i18n="landing.links">快捷入口</h3>
              <div class="link-grid">
                <a class="link-card" data-action="open-app" data-tab="config" data-i18n="landing.link.config">配置修改</a>
                <a class="link-card" data-action="open-app" data-tab="logs" data-i18n="landing.link.logs">日志查看</a>
                <a class="link-card" data-action="open-app" data-tab="about" data-i18n="landing.link.about">作者与版权说明</a>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="app" class="section">
        <div class="app-shell">
          <aside class="sidebar">
            <div class="nav-title" data-i18n="tabs.title">导航</div>
            <button class="nav-item" data-view="landing" data-i18n="tabs.landing">着陆页</button>
            <button class="nav-item" data-tab="config" data-i18n="tabs.config">配置修改</button>
            <button class="nav-item" data-tab="logs" data-i18n="tabs.logs">日志查看</button>
            <button class="nav-item" data-tab="about" data-i18n="tabs.about">作者与版权说明</button>
            <div class="nav-footer" id="navFooter">--</div>
          </aside>
          <div>
            <div id="warningBox" class="warning" style="display:none; margin-bottom:16px;">
              <div data-i18n="auth.default_password">默认密码仍在使用，请尽快修改 webui.password 并重启 WebUI。</div>
            </div>

            <div id="loginBox" class="card login">
              <h2 data-i18n="auth.title">解锁控制台</h2>
              <p class="muted" data-i18n="auth.subtitle">请输入 WebUI 密码以继续操作。</p>
              <input id="passwordInput" type="password" data-i18n-placeholder="auth.placeholder" placeholder="WebUI password" />
              <button id="loginBtn" class="btn primary" data-i18n="auth.sign_in">登录</button>
              <div class="status" id="loginStatus"></div>
            </div>

            <div id="appContent" style="display:none;">
              <div id="tab-config" class="tab">
                <div class="card" style="margin-bottom:18px;">
                  <h2 data-i18n="config.title">配置修改</h2>
                  <p class="muted" data-i18n="config.subtitle">按分类逐项调整配置，保存后自动触发热更新。</p>
                  <div class="toolbar">
                    <button id="saveFormBtn" class="btn primary" data-i18n="config.save">保存并刷新</button>
                  </div>
                  <div class="status" id="saveStatus"></div>
                </div>
                <div id="formSections" class="field-grid"></div>
              </div>

              <div id="tab-logs" class="tab">
                <div class="card">
                  <div class="panel-row">
                    <div>
                      <h2 data-i18n="logs.title">日志查看</h2>
                      <p class="muted" data-i18n="logs.subtitle">实时查看 bot 日志尾部输出。</p>
                    </div>
                    <div class="panel-row-controls">
                      <label class="toggle">
                        <input id="autoLogToggle" type="checkbox" checked />
                        <span data-i18n="logs.auto">自动刷新</span>
                      </label>
                      <select id="logInterval">
                        <option value="3000">3s</option>
                        <option value="5000" selected>5s</option>
                        <option value="10000">10s</option>
                        <option value="30000">30s</option>
                      </select>
                      <button id="refreshLogsBtn" class="btn ghost" data-i18n="logs.refresh">刷新</button>
                    </div>
                  </div>
                  <div id="logPreview" class="mono-block">Logs will appear here.</div>
                </div>
              </div>

              <div id="tab-about" class="tab">
                <div class="card">
                  <h2 data-i18n="about.title">作者与版权说明</h2>
                  <p class="muted" data-i18n="about.subtitle">关于项目作者与开源协议。</p>
                  <div class="panel" style="margin-top:16px;">
                    <div class="panel-row">
                      <h3 data-i18n="about.author">作者</h3>
                      <span class="badge" data-i18n="about.author_name">Null</span>
                    </div>
                    <p class="muted" data-i18n="about.copyright">Copyright (c) 2025 Null</p>
                  </div>
                  <div class="panel" style="margin-top:16px;">
                    <div class="panel-row">
                      <h3 data-i18n="about.license">开源协议</h3>
                      <span class="badge" data-i18n="about.license_name">MIT License</span>
                    </div>
                    <p class="muted" data-i18n="about.license_summary">允许自由使用、修改与分发，但需保留版权声明与许可证文本。</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <footer data-i18n="footer">Warm console for precise config edits.</footer>
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
    const appContent = document.getElementById('appContent');
    const loginBtn = document.getElementById('loginBtn');
    const logoutBtn = document.getElementById('logoutBtn');
    const saveFormBtn = document.getElementById('saveFormBtn');
    const refreshLogsBtn = document.getElementById('refreshLogsBtn');
    const autoLogToggle = document.getElementById('autoLogToggle');
    const logInterval = document.getElementById('logInterval');
    const passwordInput = document.getElementById('passwordInput');
    const loginStatus = document.getElementById('loginStatus');
    const saveStatus = document.getElementById('saveStatus');
    const logPreview = document.getElementById('logPreview');
    const formSections = document.getElementById('formSections');
    const statusPill = document.getElementById('statusPill');
    const navFooter = document.getElementById('navFooter');
    const botStartBtn = document.getElementById('botStartBtn');
    const botStopBtn = document.getElementById('botStopBtn');
    const botStatus = document.getElementById('botStatus');
    const botHint = document.getElementById('botHint');
    const botStateBadge = document.getElementById('botStateBadge');
    const landingLoginBox = document.getElementById('landingLoginBox');
    const landingPasswordInput = document.getElementById('landingPasswordInput');
    const landingLoginBtn = document.getElementById('landingLoginBtn');
    const landingLoginStatus = document.getElementById('landingLoginStatus');
    const themeToggle = document.getElementById('themeToggle');
    const langToggle = document.getElementById('langToggle');

    const LANG_COOKIE = 'undefined_webui_lang';
    const THEME_COOKIE = 'undefined_webui_theme';
    const TOKEN_COOKIE = 'undefined_webui_token';

    let logTimer = null;
    let isAuthenticated = false;
    let currentTab = 'config';
    let lastSummary = {};

    const I18N = {
      zh: {
        'landing.kicker': 'WebUI',
        'landing.title': '配置控制台',
        'landing.subtitle': '提供配置管理、日志追踪与运行控制的统一入口。',
        'landing.cta': '进入控制台',
        'landing.logs': '日志查看',
        'landing.about': '作者与版权',
        'landing.links': '快捷入口',
        'landing.link.config': '配置修改',
        'landing.link.logs': '日志查看',
        'landing.link.about': '作者与版权说明',
        'tabs.title': '导航',
        'tabs.landing': '着陆页',
        'tabs.config': '配置修改',
        'tabs.logs': '日志查看',
        'tabs.about': '作者与版权说明',
        'auth.title': '解锁控制台',
        'auth.subtitle': '请输入 WebUI 密码以继续操作。',
        'auth.placeholder': 'WebUI 密码',
        'auth.sign_in': '登录',
        'auth.sign_out': '退出登录',
        'auth.checking': '正在验证...',
        'auth.success': '登录成功。',
        'auth.invalid': '密码错误。',
        'auth.default_password': '默认密码仍在使用，请尽快修改 webui.password 并重启 WebUI。',
        'config.title': '配置修改',
        'config.subtitle': '按分类逐项调整配置，保存后自动触发热更新。',
        'config.save': '保存并刷新',
        'config.no_changes': '没有可保存的修改。',
        'config.saved': '保存成功，配置已刷新。',
        'config.saving': '正在保存...',
        'logs.title': '日志查看',
        'logs.subtitle': '实时查看 bot 日志尾部输出。',
        'logs.auto': '自动刷新',
        'logs.refresh': '刷新',
        'logs.locked': '需要登录后查看日志。',
        'about.title': '作者与版权说明',
        'about.subtitle': '关于项目作者与开源协议。',
        'about.author': '作者',
        'about.author_name': 'Null',
        'about.copyright': 'Copyright (c) 2025 Null',
        'about.license': '开源协议',
        'about.license_name': 'MIT License',
        'about.license_summary': '允许自由使用、修改与分发，但需保留版权声明与许可证文本。',
        'footer': 'Warm console for precise config edits.',
        'bot.title': 'Bot 控制',
        'bot.start': '启动',
        'bot.stop': '停止',
        'bot.running': '运行中',
        'bot.stopped': '已停止',
        'bot.locked': '已锁定',
        'bot.starting': '正在启动...',
        'bot.stopping': '正在停止...',
        'bot.hint.running': '当前由 WebUI 子进程托管运行。',
        'bot.hint.stopped': '点击启动以运行机器人。',
        'bot.hint.locked': '请先登录后操作。',
        'field.core.bot_qq': '机器人 QQ',
        'field.core.superadmin_qq': '超级管理员 QQ',
        'field.core.admin_qq': '管理员 QQ 列表',
        'field.core.forward_proxy_qq': '转发代理 QQ',
        'field.onebot.ws_url': 'OneBot WebSocket 地址',
        'field.onebot.token': 'OneBot Token',
        'field.models.chat.api_url': 'Chat API URL',
        'field.models.chat.api_key': 'Chat API Key',
        'field.models.chat.model_name': 'Chat 模型名',
        'field.models.chat.max_tokens': 'Chat Max Tokens',
        'field.models.chat.thinking_enabled': 'Chat Thinking',
        'field.models.chat.thinking_budget_tokens': 'Chat Thinking Budget',
        'field.models.chat.deepseek_new_cot_support': 'Chat DeepSeek 新 CoT',
        'field.models.vision.api_url': 'Vision API URL',
        'field.models.vision.api_key': 'Vision API Key',
        'field.models.vision.model_name': 'Vision 模型名',
        'field.models.vision.thinking_enabled': 'Vision Thinking',
        'field.models.vision.thinking_budget_tokens': 'Vision Thinking Budget',
        'field.models.vision.deepseek_new_cot_support': 'Vision DeepSeek 新 CoT',
        'field.models.security.api_url': 'Security API URL',
        'field.models.security.api_key': 'Security API Key',
        'field.models.security.model_name': 'Security 模型名',
        'field.models.security.max_tokens': 'Security Max Tokens',
        'field.models.security.thinking_enabled': 'Security Thinking',
        'field.models.security.thinking_budget_tokens': 'Security Thinking Budget',
        'field.models.security.deepseek_new_cot_support': 'Security DeepSeek 新 CoT',
        'field.models.agent.api_url': 'Agent API URL',
        'field.models.agent.api_key': 'Agent API Key',
        'field.models.agent.model_name': 'Agent 模型名',
        'field.models.agent.max_tokens': 'Agent Max Tokens',
        'field.models.agent.thinking_enabled': 'Agent Thinking',
        'field.models.agent.thinking_budget_tokens': 'Agent Thinking Budget',
        'field.models.agent.deepseek_new_cot_support': 'Agent DeepSeek 新 CoT',
        'field.logging.level': '日志等级',
        'field.logging.file_path': '日志文件路径',
        'field.logging.max_size_mb': '单文件大小 MB',
        'field.logging.backup_count': '日志备份数量',
        'field.logging.log_thinking': '记录 Thinking',
        'field.tools.sanitize': '工具净化',
        'field.tools.description_max_len': '工具描述最大长度',
        'field.tools.sanitize_verbose': '净化详情输出',
        'field.tools.description_preview_len': '工具描述预览长度',
        'field.skills.hot_reload': '技能热重载',
        'field.skills.hot_reload_interval': '热重载间隔',
        'field.skills.hot_reload_debounce': '热重载防抖',
        'field.skills.intro_autogen_enabled': 'Intro 自动生成',
        'field.skills.intro_autogen_queue_interval': 'Intro 队列间隔',
        'field.skills.intro_autogen_max_tokens': 'Intro 最大 Tokens',
        'field.skills.intro_hash_path': 'Intro Hash 路径',
        'field.skills.prefetch_tools': '预加载工具',
        'field.skills.prefetch_tools_hide': '隐藏预加载工具',
        'field.search.searxng_url': 'SearXNG URL',
        'field.proxy.use_proxy': '启用代理',
        'field.proxy.http_proxy': 'HTTP Proxy',
        'field.proxy.https_proxy': 'HTTPS Proxy',
        'field.weather.api_key': '天气 API Key',
        'field.xxapi.api_token': 'XXAPI Token',
        'field.token_usage.max_size_mb': 'Token 统计单文件 MB',
        'field.token_usage.max_archives': 'Token 归档数量',
        'field.token_usage.max_total_mb': 'Token 总容量 MB',
        'field.token_usage.archive_prune_mode': 'Token 归档策略',
        'field.mcp.config_path': 'MCP 配置路径',
        'field.webui.url': 'WebUI 地址',
        'field.webui.port': 'WebUI 端口',
        'field.webui.password': 'WebUI 密码',
        'section.core': '核心配置',
        'section.onebot': 'OneBot',
        'section.models.chat': '模型 - Chat',
        'section.models.vision': '模型 - Vision',
        'section.models.security': '模型 - Security',
        'section.models.agent': '模型 - Agent',
        'section.logging': '日志',
        'section.tools': '工具',
        'section.skills': '技能',
        'section.search': '搜索',
        'section.proxy': '代理',
        'section.weather': '天气',
        'section.xxapi': 'XXAPI',
        'section.token_usage': 'Token 统计',
        'section.mcp': 'MCP',
        'section.webui': 'WebUI',
        'placeholder.list_int': '用英文逗号分隔',
        'placeholder.list_str': '例如: tool_a, tool_b',
      },
      en: {
        'landing.kicker': 'WebUI',
        'landing.title': 'Config Console',
        'landing.subtitle': 'Unified entry for config, logs, and runtime control.',
        'landing.cta': 'Open Console',
        'landing.logs': 'View Logs',
        'landing.about': 'About & License',
        'landing.links': 'Quick Links',
        'landing.link.config': 'Config Editor',
        'landing.link.logs': 'Log Viewer',
        'landing.link.about': 'Author & License',
        'tabs.title': 'Navigation',
        'tabs.landing': 'Landing',
        'tabs.config': 'Config',
        'tabs.logs': 'Logs',
        'tabs.about': 'About',
        'auth.title': 'Unlock Console',
        'auth.subtitle': 'Enter the WebUI password to continue.',
        'auth.placeholder': 'WebUI password',
        'auth.sign_in': 'Sign in',
        'auth.sign_out': 'Sign out',
        'auth.checking': 'Checking...',
        'auth.success': 'Signed in.',
        'auth.invalid': 'Invalid password.',
        'auth.default_password': 'Default password is active. Update webui.password and restart WebUI.',
        'config.title': 'Config Editor',
        'config.subtitle': 'Update settings by category. Save triggers hot reload.',
        'config.save': 'Save & Reload',
        'config.no_changes': 'No changes to save.',
        'config.saved': 'Saved and refreshed.',
        'config.saving': 'Saving...',
        'logs.title': 'Log Viewer',
        'logs.subtitle': 'Tail the latest bot logs in real time.',
        'logs.auto': 'Auto refresh',
        'logs.refresh': 'Refresh',
        'logs.locked': 'Sign in to view logs.',
        'about.title': 'Author & License',
        'about.subtitle': 'Project author and open-source terms.',
        'about.author': 'Author',
        'about.author_name': 'Null',
        'about.copyright': 'Copyright (c) 2025 Null',
        'about.license': 'License',
        'about.license_name': 'MIT License',
        'about.license_summary': 'Free use, modification, and distribution with copyright notice included.',
        'footer': 'Warm console for precise config edits.',
        'bot.title': 'Bot Control',
        'bot.start': 'Start',
        'bot.stop': 'Stop',
        'bot.running': 'Running',
        'bot.stopped': 'Stopped',
        'bot.locked': 'Locked',
        'bot.starting': 'Starting...',
        'bot.stopping': 'Stopping...',
        'bot.hint.running': 'Managed by a WebUI child process.',
        'bot.hint.stopped': 'Click start to run the bot.',
        'bot.hint.locked': 'Sign in to control the bot.',
        'field.core.bot_qq': 'Bot QQ',
        'field.core.superadmin_qq': 'Superadmin QQ',
        'field.core.admin_qq': 'Admin QQ list',
        'field.core.forward_proxy_qq': 'Forward proxy QQ',
        'field.onebot.ws_url': 'OneBot WebSocket URL',
        'field.onebot.token': 'OneBot Token',
        'field.models.chat.api_url': 'Chat API URL',
        'field.models.chat.api_key': 'Chat API Key',
        'field.models.chat.model_name': 'Chat Model Name',
        'field.models.chat.max_tokens': 'Chat Max Tokens',
        'field.models.chat.thinking_enabled': 'Chat Thinking',
        'field.models.chat.thinking_budget_tokens': 'Chat Thinking Budget',
        'field.models.chat.deepseek_new_cot_support': 'Chat DeepSeek new CoT',
        'field.models.vision.api_url': 'Vision API URL',
        'field.models.vision.api_key': 'Vision API Key',
        'field.models.vision.model_name': 'Vision Model Name',
        'field.models.vision.thinking_enabled': 'Vision Thinking',
        'field.models.vision.thinking_budget_tokens': 'Vision Thinking Budget',
        'field.models.vision.deepseek_new_cot_support': 'Vision DeepSeek new CoT',
        'field.models.security.api_url': 'Security API URL',
        'field.models.security.api_key': 'Security API Key',
        'field.models.security.model_name': 'Security Model Name',
        'field.models.security.max_tokens': 'Security Max Tokens',
        'field.models.security.thinking_enabled': 'Security Thinking',
        'field.models.security.thinking_budget_tokens': 'Security Thinking Budget',
        'field.models.security.deepseek_new_cot_support': 'Security DeepSeek new CoT',
        'field.models.agent.api_url': 'Agent API URL',
        'field.models.agent.api_key': 'Agent API Key',
        'field.models.agent.model_name': 'Agent Model Name',
        'field.models.agent.max_tokens': 'Agent Max Tokens',
        'field.models.agent.thinking_enabled': 'Agent Thinking',
        'field.models.agent.thinking_budget_tokens': 'Agent Thinking Budget',
        'field.models.agent.deepseek_new_cot_support': 'Agent DeepSeek new CoT',
        'field.logging.level': 'Log Level',
        'field.logging.file_path': 'Log File Path',
        'field.logging.max_size_mb': 'Max File Size MB',
        'field.logging.backup_count': 'Backup Count',
        'field.logging.log_thinking': 'Log Thinking',
        'field.tools.sanitize': 'Tools Sanitize',
        'field.tools.description_max_len': 'Tools Description Max',
        'field.tools.sanitize_verbose': 'Sanitize Verbose',
        'field.tools.description_preview_len': 'Tools Preview Length',
        'field.skills.hot_reload': 'Skills Hot Reload',
        'field.skills.hot_reload_interval': 'Hot Reload Interval',
        'field.skills.hot_reload_debounce': 'Hot Reload Debounce',
        'field.skills.intro_autogen_enabled': 'Intro Auto-gen',
        'field.skills.intro_autogen_queue_interval': 'Intro Queue Interval',
        'field.skills.intro_autogen_max_tokens': 'Intro Max Tokens',
        'field.skills.intro_hash_path': 'Intro Hash Path',
        'field.skills.prefetch_tools': 'Prefetch Tools',
        'field.skills.prefetch_tools_hide': 'Hide Prefetched Tools',
        'field.search.searxng_url': 'SearXNG URL',
        'field.proxy.use_proxy': 'Use Proxy',
        'field.proxy.http_proxy': 'HTTP Proxy',
        'field.proxy.https_proxy': 'HTTPS Proxy',
        'field.weather.api_key': 'Weather API Key',
        'field.xxapi.api_token': 'XXAPI Token',
        'field.token_usage.max_size_mb': 'Token File Size MB',
        'field.token_usage.max_archives': 'Token Archive Count',
        'field.token_usage.max_total_mb': 'Token Total MB',
        'field.token_usage.archive_prune_mode': 'Token Prune Mode',
        'field.mcp.config_path': 'MCP Config Path',
        'field.webui.url': 'WebUI Host',
        'field.webui.port': 'WebUI Port',
        'field.webui.password': 'WebUI Password',
        'section.core': 'Core',
        'section.onebot': 'OneBot',
        'section.models.chat': 'Model - Chat',
        'section.models.vision': 'Model - Vision',
        'section.models.security': 'Model - Security',
        'section.models.agent': 'Model - Agent',
        'section.logging': 'Logging',
        'section.tools': 'Tools',
        'section.skills': 'Skills',
        'section.search': 'Search',
        'section.proxy': 'Proxy',
        'section.weather': 'Weather',
        'section.xxapi': 'XXAPI',
        'section.token_usage': 'Token Usage',
        'section.mcp': 'MCP',
        'section.webui': 'WebUI',
        'placeholder.list_int': 'Comma-separated',
        'placeholder.list_str': 'e.g. tool_a, tool_b',
      }
    };

    const FORM_DEFINITION = [
      {
        titleKey: 'section.core',
        fields: [
          { path: 'core.bot_qq', labelKey: 'field.core.bot_qq', type: 'number' },
          { path: 'core.superadmin_qq', labelKey: 'field.core.superadmin_qq', type: 'number' },
          { path: 'core.admin_qq', labelKey: 'field.core.admin_qq', type: 'list-int', placeholderKey: 'placeholder.list_int' },
          { path: 'core.forward_proxy_qq', labelKey: 'field.core.forward_proxy_qq', type: 'number' },
        ]
      },
      {
        titleKey: 'section.onebot',
        fields: [
          { path: 'onebot.ws_url', labelKey: 'field.onebot.ws_url', type: 'string' },
          { path: 'onebot.token', labelKey: 'field.onebot.token', type: 'secret' }
        ]
      },
      {
        titleKey: 'section.models.chat',
        fields: [
          { path: 'models.chat.api_url', labelKey: 'field.models.chat.api_url', type: 'string' },
          { path: 'models.chat.api_key', labelKey: 'field.models.chat.api_key', type: 'secret' },
          { path: 'models.chat.model_name', labelKey: 'field.models.chat.model_name', type: 'string' },
          { path: 'models.chat.max_tokens', labelKey: 'field.models.chat.max_tokens', type: 'number' },
          { path: 'models.chat.thinking_enabled', labelKey: 'field.models.chat.thinking_enabled', type: 'bool' },
          { path: 'models.chat.thinking_budget_tokens', labelKey: 'field.models.chat.thinking_budget_tokens', type: 'number' },
          { path: 'models.chat.deepseek_new_cot_support', labelKey: 'field.models.chat.deepseek_new_cot_support', type: 'bool' },
        ]
      },
      {
        titleKey: 'section.models.vision',
        fields: [
          { path: 'models.vision.api_url', labelKey: 'field.models.vision.api_url', type: 'string' },
          { path: 'models.vision.api_key', labelKey: 'field.models.vision.api_key', type: 'secret' },
          { path: 'models.vision.model_name', labelKey: 'field.models.vision.model_name', type: 'string' },
          { path: 'models.vision.thinking_enabled', labelKey: 'field.models.vision.thinking_enabled', type: 'bool' },
          { path: 'models.vision.thinking_budget_tokens', labelKey: 'field.models.vision.thinking_budget_tokens', type: 'number' },
          { path: 'models.vision.deepseek_new_cot_support', labelKey: 'field.models.vision.deepseek_new_cot_support', type: 'bool' },
        ]
      },
      {
        titleKey: 'section.models.security',
        fields: [
          { path: 'models.security.api_url', labelKey: 'field.models.security.api_url', type: 'string' },
          { path: 'models.security.api_key', labelKey: 'field.models.security.api_key', type: 'secret' },
          { path: 'models.security.model_name', labelKey: 'field.models.security.model_name', type: 'string' },
          { path: 'models.security.max_tokens', labelKey: 'field.models.security.max_tokens', type: 'number' },
          { path: 'models.security.thinking_enabled', labelKey: 'field.models.security.thinking_enabled', type: 'bool' },
          { path: 'models.security.thinking_budget_tokens', labelKey: 'field.models.security.thinking_budget_tokens', type: 'number' },
          { path: 'models.security.deepseek_new_cot_support', labelKey: 'field.models.security.deepseek_new_cot_support', type: 'bool' },
        ]
      },
      {
        titleKey: 'section.models.agent',
        fields: [
          { path: 'models.agent.api_url', labelKey: 'field.models.agent.api_url', type: 'string' },
          { path: 'models.agent.api_key', labelKey: 'field.models.agent.api_key', type: 'secret' },
          { path: 'models.agent.model_name', labelKey: 'field.models.agent.model_name', type: 'string' },
          { path: 'models.agent.max_tokens', labelKey: 'field.models.agent.max_tokens', type: 'number' },
          { path: 'models.agent.thinking_enabled', labelKey: 'field.models.agent.thinking_enabled', type: 'bool' },
          { path: 'models.agent.thinking_budget_tokens', labelKey: 'field.models.agent.thinking_budget_tokens', type: 'number' },
          { path: 'models.agent.deepseek_new_cot_support', labelKey: 'field.models.agent.deepseek_new_cot_support', type: 'bool' },
        ]
      },
      {
        titleKey: 'section.logging',
        fields: [
          { path: 'logging.level', labelKey: 'field.logging.level', type: 'string' },
          { path: 'logging.file_path', labelKey: 'field.logging.file_path', type: 'string' },
          { path: 'logging.max_size_mb', labelKey: 'field.logging.max_size_mb', type: 'number' },
          { path: 'logging.backup_count', labelKey: 'field.logging.backup_count', type: 'number' },
          { path: 'logging.log_thinking', labelKey: 'field.logging.log_thinking', type: 'bool' }
        ]
      },
      {
        titleKey: 'section.tools',
        fields: [
          { path: 'tools.sanitize', labelKey: 'field.tools.sanitize', type: 'bool' },
          { path: 'tools.description_max_len', labelKey: 'field.tools.description_max_len', type: 'number' },
          { path: 'tools.sanitize_verbose', labelKey: 'field.tools.sanitize_verbose', type: 'bool' },
          { path: 'tools.description_preview_len', labelKey: 'field.tools.description_preview_len', type: 'number' }
        ]
      },
      {
        titleKey: 'section.skills',
        fields: [
          { path: 'skills.hot_reload', labelKey: 'field.skills.hot_reload', type: 'bool' },
          { path: 'skills.hot_reload_interval', labelKey: 'field.skills.hot_reload_interval', type: 'number' },
          { path: 'skills.hot_reload_debounce', labelKey: 'field.skills.hot_reload_debounce', type: 'number' },
          { path: 'skills.intro_autogen_enabled', labelKey: 'field.skills.intro_autogen_enabled', type: 'bool' },
          { path: 'skills.intro_autogen_queue_interval', labelKey: 'field.skills.intro_autogen_queue_interval', type: 'number' },
          { path: 'skills.intro_autogen_max_tokens', labelKey: 'field.skills.intro_autogen_max_tokens', type: 'number' },
          { path: 'skills.intro_hash_path', labelKey: 'field.skills.intro_hash_path', type: 'string' },
          { path: 'skills.prefetch_tools', labelKey: 'field.skills.prefetch_tools', type: 'list-str', placeholderKey: 'placeholder.list_str' },
          { path: 'skills.prefetch_tools_hide', labelKey: 'field.skills.prefetch_tools_hide', type: 'bool' }
        ]
      },
      {
        titleKey: 'section.search',
        fields: [
          { path: 'search.searxng_url', labelKey: 'field.search.searxng_url', type: 'string' }
        ]
      },
      {
        titleKey: 'section.proxy',
        fields: [
          { path: 'proxy.use_proxy', labelKey: 'field.proxy.use_proxy', type: 'bool' },
          { path: 'proxy.http_proxy', labelKey: 'field.proxy.http_proxy', type: 'string' },
          { path: 'proxy.https_proxy', labelKey: 'field.proxy.https_proxy', type: 'string' }
        ]
      },
      {
        titleKey: 'section.weather',
        fields: [
          { path: 'weather.api_key', labelKey: 'field.weather.api_key', type: 'secret' }
        ]
      },
      {
        titleKey: 'section.xxapi',
        fields: [
          { path: 'xxapi.api_token', labelKey: 'field.xxapi.api_token', type: 'secret' }
        ]
      },
      {
        titleKey: 'section.token_usage',
        fields: [
          { path: 'token_usage.max_size_mb', labelKey: 'field.token_usage.max_size_mb', type: 'number' },
          { path: 'token_usage.max_archives', labelKey: 'field.token_usage.max_archives', type: 'number' },
          { path: 'token_usage.max_total_mb', labelKey: 'field.token_usage.max_total_mb', type: 'number' },
          { path: 'token_usage.archive_prune_mode', labelKey: 'field.token_usage.archive_prune_mode', type: 'string' }
        ]
      },
      {
        titleKey: 'section.mcp',
        fields: [
          { path: 'mcp.config_path', labelKey: 'field.mcp.config_path', type: 'string' }
        ]
      },
      {
        titleKey: 'section.webui',
        fields: [
          { path: 'webui.url', labelKey: 'field.webui.url', type: 'string' },
          { path: 'webui.port', labelKey: 'field.webui.port', type: 'number' },
          { path: 'webui.password', labelKey: 'field.webui.password', type: 'secret' }
        ]
      }
    ];

    let formState = {};

    function getCookie(name) {
      const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
      return match ? decodeURIComponent(match[2]) : '';
    }

    function setCookie(name, value, days) {
      const maxAge = days ? days * 24 * 60 * 60 : 3600 * 24 * 365;
      document.cookie = `${name}=${encodeURIComponent(value)}; Max-Age=${maxAge}; Path=/; SameSite=Lax`;
    }

    function deleteCookie(name) {
      document.cookie = `${name}=; Max-Age=0; Path=/; SameSite=Lax`;
    }

    function t(key) {
      const lang = getCurrentLang();
      return I18N[lang][key] || key;
    }

    function getCurrentLang() {
      const stored = getCookie(LANG_COOKIE);
      if (stored === 'en') {
        return 'en';
      }
      return 'zh';
    }

    function getCurrentTheme() {
      const stored = getCookie(THEME_COOKIE);
      if (stored === 'dark') {
        return 'dark';
      }
      return 'light';
    }

    function applyTheme() {
      const theme = getCurrentTheme();
      document.documentElement.setAttribute('data-theme', theme);
      themeToggle.textContent = theme === 'dark' ? 'Dark' : 'Light';
    }

    function applyLang() {
      const lang = getCurrentLang();
      document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
      langToggle.textContent = lang === 'en' ? 'EN' : '中文';
      document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        el.textContent = t(key);
      });
      document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        const key = el.getAttribute('data-i18n-placeholder');
        el.setAttribute('placeholder', t(key));
      });
      renderForm(lastSummary);
    }

    function showSection(view) {
      landing.classList.toggle('active', view === 'landing');
      app.classList.toggle('active', view === 'app');
      if (view === 'landing') {
        stopLogAutoRefresh();
      }
    }

    function setNavActive(target) {
      document.querySelectorAll('.nav-item').forEach(btn => {
        const isLanding = btn.dataset.view === 'landing';
        const isActive = isLanding ? target === 'landing' : btn.dataset.tab === target;
        btn.classList.toggle('active', isActive);
      });
    }

    function showTab(tab) {
      currentTab = tab;
      setNavActive(tab);
      document.querySelectorAll('.tab').forEach(section => {
        section.classList.toggle('active', section.id === `tab-${tab}`);
      });
      if (tab === 'logs') {
        startLogAutoRefresh();
      } else {
        stopLogAutoRefresh();
      }
      if (tab === 'config' && isAuthenticated && Object.keys(lastSummary).length === 0) {
        loadSummary();
      }
    }

    async function api(path, options = {}) {
      const headers = Object.assign({}, options.headers || {});
      if (!headers['Content-Type'] && options.method && options.method !== 'GET') {
        headers['Content-Type'] = 'application/json';
      }
      const token = getCookie(TOKEN_COOKIE);
      if (token) {
        headers['X-Auth-Token'] = token;
      }
      const res = await fetch(path, { credentials: 'same-origin', ...options, headers });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || data.message || 'Request failed');
      }
      return data;
    }

    function translateError(message) {
      if (!message) {
        return message;
      }
      if (message === 'Invalid password') {
        return t('auth.invalid');
      }
      if (message === 'Unauthorized') {
        return t('bot.locked');
      }
      return message;
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
        if (value === '' || value === null || value === undefined) {
          return null;
        }
        const num = Number(value);
        return Number.isFinite(num) ? num : null;
      }
      if (type === 'list-int') {
        if (!value) {
          return [];
        }
        return value.split(',').map(item => parseInt(item.trim(), 10)).filter(n => Number.isFinite(n));
      }
      if (type === 'list-str') {
        if (!value) {
          return [];
        }
        return value.split(',').map(item => item.trim()).filter(Boolean);
      }
      return value ?? '';
    }

    function renderForm(summary) {
      formSections.innerHTML = '';
      formState = {};
      FORM_DEFINITION.forEach(section => {
        const sectionWrap = document.createElement('div');
        sectionWrap.className = 'panel form-section';
        const title = document.createElement('h3');
        title.className = 'section-title';
        title.textContent = t(section.titleKey);
        sectionWrap.appendChild(title);
        const fieldsWrap = document.createElement('div');
        fieldsWrap.className = 'field-grid';
        section.fields.forEach(field => {
          const fieldWrap = document.createElement('div');
          fieldWrap.className = 'field';
          const label = document.createElement('label');
          label.textContent = t(field.labelKey);
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
            } else if (field.type === 'secret') {
              input.type = 'password';
            } else {
              input.type = 'text';
            }
          }
          const value = getValueByPath(summary, field.path);
          const normalized = normalizeFormValue(value, field.type);
          if (field.type === 'list-int' || field.type === 'list-str') {
            input.value = Array.isArray(normalized) ? normalized.join(', ') : '';
          } else if (field.type === 'bool') {
            input.value = normalized ? 'true' : 'false';
          } else if (normalized !== null && normalized !== undefined) {
            input.value = normalized;
          }
          if (field.placeholderKey) {
            input.placeholder = t(field.placeholderKey);
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
      if (!autoLogToggle || !autoLogToggle.checked || !isAuthenticated || currentTab !== 'logs') {
        return;
      }
      const interval = Number(logInterval?.value) || 5000;
      logTimer = setInterval(() => {
        loadLogs();
      }, interval);
    }

    async function checkSession() {
      const data = await api('/api/session');
      isAuthenticated = Boolean(data.authenticated);
      warningBox.style.display = data.using_default_password ? 'flex' : 'none';
      statusPill.textContent = data.summary || 'config.toml';
      navFooter.textContent = data.summary || '';
      logoutBtn.style.display = isAuthenticated ? 'inline-flex' : 'none';
      if (landingLoginBox) {
        landingLoginBox.style.display = isAuthenticated ? 'none' : 'block';
      }
      if (isAuthenticated) {
        loginBox.style.display = 'none';
        appContent.style.display = 'block';
        await loadSummary();
        if (currentTab === 'logs') {
          await loadLogs();
          startLogAutoRefresh();
        }
      } else {
        loginBox.style.display = 'grid';
        appContent.style.display = 'none';
        stopLogAutoRefresh();
      }
    }

    async function loadSummary() {
      if (!isAuthenticated) {
        return;
      }
      const data = await api('/api/config/summary');
      lastSummary = data.data || {};
      renderForm(lastSummary);
    }

    async function loadLogs() {
      if (!isAuthenticated) {
        logPreview.textContent = t('logs.locked');
        return;
      }
      const data = await api('/api/logs');
      logPreview.textContent = data.content || '';
    }

    async function saveForm() {
      if (!isAuthenticated) {
        return;
      }
      const patch = {};
      formSections.querySelectorAll('[data-path]').forEach(input => {
        const path = input.dataset.path;
        const type = input.dataset.type;
        const normalized = normalizeFormValue(input.value, type);
        if (normalized === null && type === 'number') {
          return;
        }
        const original = formState[path];
        if (JSON.stringify(normalized) !== JSON.stringify(original)) {
          patch[path] = normalized;
        }
      });
      if (Object.keys(patch).length === 0) {
        saveStatus.textContent = t('config.no_changes');
        return;
      }
      saveStatus.textContent = t('config.saving');
      try {
        await api('/api/patch', {
          method: 'POST',
          body: JSON.stringify({ patch })
        });
        await loadSummary();
        saveStatus.textContent = t('config.saved');
      } catch (err) {
        saveStatus.textContent = translateError(err.message);
      }
    }

    async function loadBotStatus() {
      try {
        const data = await api('/api/bot/status');
        const running = Boolean(data.running);
        botStateBadge.textContent = running ? t('bot.running') : t('bot.stopped');
        botStateBadge.classList.toggle('warn', !running);
        botStatus.textContent = data.pid ? `PID ${data.pid}` : '--';
        botHint.textContent = running ? t('bot.hint.running') : t('bot.hint.stopped');
        botStartBtn.disabled = running || !isAuthenticated;
        botStopBtn.disabled = !running || !isAuthenticated;
        if (!isAuthenticated) {
          botHint.textContent = t('bot.hint.locked');
        }
      } catch (err) {
        botStateBadge.textContent = t('bot.locked');
        botHint.textContent = translateError(err.message);
      }
    }

    loginBtn?.addEventListener('click', async () => {
      loginStatus.textContent = t('auth.checking');
      try {
        const data = await api('/api/login', {
          method: 'POST',
          body: JSON.stringify({ password: passwordInput.value })
        });
        if (data.token) {
          setCookie(TOKEN_COOKIE, data.token, 7);
        }
        loginStatus.textContent = t('auth.success');
        await checkSession();
        await loadBotStatus();
      } catch (err) {
        loginStatus.textContent = translateError(err.message);
      }
    });

    landingLoginBtn?.addEventListener('click', async () => {
      if (!landingLoginStatus) {
        return;
      }
      landingLoginStatus.textContent = t('auth.checking');
      try {
        const data = await api('/api/login', {
          method: 'POST',
          body: JSON.stringify({ password: landingPasswordInput?.value || '' })
        });
        if (data.token) {
          setCookie(TOKEN_COOKIE, data.token, 7);
        }
        landingLoginStatus.textContent = t('auth.success');
        await checkSession();
        await loadBotStatus();
      } catch (err) {
        landingLoginStatus.textContent = translateError(err.message);
      }
    });

    logoutBtn?.addEventListener('click', async () => {
      try {
        await api('/api/logout', { method: 'POST' });
      } finally {
        deleteCookie(TOKEN_COOKIE);
        await checkSession();
        await loadBotStatus();
      }
    });

    saveFormBtn?.addEventListener('click', saveForm);
    refreshLogsBtn?.addEventListener('click', loadLogs);
    autoLogToggle?.addEventListener('change', startLogAutoRefresh);
    logInterval?.addEventListener('change', startLogAutoRefresh);

    botStartBtn?.addEventListener('click', async () => {
      botHint.textContent = t('bot.starting');
      try {
        await api('/api/bot/start', { method: 'POST' });
      } catch (err) {
        botHint.textContent = translateError(err.message);
      }
      await loadBotStatus();
    });

    botStopBtn?.addEventListener('click', async () => {
      botHint.textContent = t('bot.stopping');
      try {
        await api('/api/bot/stop', { method: 'POST' });
      } catch (err) {
        botHint.textContent = translateError(err.message);
      }
      await loadBotStatus();
    });

    document.querySelectorAll('[data-action="open-app"]').forEach(btn => {
      btn.addEventListener('click', () => {
        showSection('app');
        const tab = btn.dataset.tab || 'config';
        showTab(tab);
        checkSession().then(loadBotStatus);
      });
    });

    document.querySelectorAll('.nav-item').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.view === 'landing') {
          showSection('landing');
          setNavActive('landing');
          checkSession().then(loadBotStatus);
          return;
        }
        showSection('app');
        showTab(btn.dataset.tab || 'config');
      });
    });

    themeToggle?.addEventListener('click', () => {
      const next = getCurrentTheme() === 'dark' ? 'light' : 'dark';
      setCookie(THEME_COOKIE, next, 365);
      applyTheme();
    });

    langToggle?.addEventListener('click', () => {
      const next = getCurrentLang() === 'zh' ? 'en' : 'zh';
      setCookie(LANG_COOKIE, next, 365);
      applyLang();
      loadBotStatus();
    });

    if (!getCookie(LANG_COOKIE)) {
      setCookie(LANG_COOKIE, 'zh', 365);
    }
    if (!getCookie(THEME_COOKIE)) {
      setCookie(THEME_COOKIE, 'light', 365);
    }
    applyTheme();
    applyLang();
    if (usingDefaultPassword) {
      warningBox.style.display = 'flex';
    }

    if (initialView === 'landing') {
      showSection('landing');
      setNavActive('landing');
      checkSession().then(loadBotStatus);
    } else {
      showSection('app');
      showTab(currentTab);
      checkSession().then(loadBotStatus);
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


def _extract_token(request: web.Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        return token
    token = request.cookies.get(TOKEN_COOKIE)
    if token:
        return token
    return request.headers.get("X-Auth-Token")


def _is_authenticated(request: web.Request) -> bool:
    sessions: SessionStore = request.app["sessions"]
    token = _extract_token(request)
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
    response = web.json_response({"ok": True, "token": token})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="Lax",
        max_age=SESSION_TTL_SECONDS,
    )
    response.set_cookie(
        TOKEN_COOKIE, token, httponly=False, samesite="Lax", max_age=SESSION_TTL_SECONDS
    )
    return response


async def _handle_logout(request: web.Request) -> web.Response:
    sessions: SessionStore = request.app["sessions"]
    token = _extract_token(request)
    sessions.revoke(token)
    response = web.json_response({"ok": True})
    response.del_cookie(SESSION_COOKIE)
    response.del_cookie(TOKEN_COOKIE)
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
    patch = body.get("patch")
    if not isinstance(patch, dict):
        return web.json_response({"error": "Invalid payload"}, status=400)
    source = _read_config_source()
    try:
        data = tomllib.loads(source.content) if source.content.strip() else {}
    except tomllib.TOMLDecodeError as exc:
        return web.json_response({"error": f"TOML parse error: {exc}"}, status=400)
    if not isinstance(data, dict):
        data = {}
    patched = _apply_patch(data, patch)
    rendered = _render_toml(patched)
    CONFIG_PATH.write_text(rendered, encoding="utf-8")
    validation_ok, validation_msg = _validate_required_config()
    if validation_ok:
        result_message = "Saved. Config looks good."
    else:
        result_message = f"Saved. Warning: {validation_msg}"
    return web.json_response({"ok": True, "message": result_message})


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


async def _handle_bot_status(request: web.Request) -> web.Response:
    controller: BotProcessController = request.app["bot"]
    return web.json_response(controller.status())


async def _handle_bot_start(request: web.Request) -> web.Response:
    if not _is_authenticated(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    controller: BotProcessController = request.app["bot"]
    try:
        status = await controller.start()
        return web.json_response(status)
    except FileNotFoundError:
        return web.json_response({"error": "uv not found"}, status=500)
    except Exception as exc:
        logger.exception("启动 bot 失败: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)


async def _handle_bot_stop(request: web.Request) -> web.Response:
    if not _is_authenticated(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    controller: BotProcessController = request.app["bot"]
    try:
        status = await controller.stop()
        return web.json_response(status)
    except Exception as exc:
        logger.exception("停止 bot 失败: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)


def _create_app(settings: WebUISettings) -> web.Application:
    app = web.Application()
    app["settings"] = settings
    app["sessions"] = SessionStore()
    app["bot"] = BotProcessController()
    app.add_routes(
        [
            web.get("/", _handle_index),
            web.get("/app", _handle_app),
            web.get("/api/session", _handle_session),
            web.post("/api/login", _handle_login),
            web.post("/api/logout", _handle_logout),
            web.get("/api/config", _handle_config_get),
            web.post("/api/config", _handle_config_post),
            web.get("/api/config/summary", _handle_summary),
            web.post("/api/patch", _handle_patch),
            web.get("/api/logs", _handle_logs),
            web.get("/api/bot/status", _handle_bot_status),
            web.post("/api/bot/start", _handle_bot_start),
            web.post("/api/bot/stop", _handle_bot_stop),
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
