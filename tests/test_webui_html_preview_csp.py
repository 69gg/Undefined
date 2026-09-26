"""HTML 预览的 CSP 契约（配置级断言，不是源码子串匹配）。

原断言把整份 webui/app.py 与 tauri.conf.json 当字符串读，再找
`"script-src 'self' 'nonce-{nonce}'; "` 这类子串——配置文件改一个字就红，
而真正的安全回归（有人加了 unsafe-inline / unsafe-eval）却未必测得到。
这里改为解析 CSP 字符串本身，逐条指令断言。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
TAURI_CONF: Final[Path] = (
    REPO_ROOT / "apps" / "undefined-console" / "src-tauri" / "tauri.conf.json"
)
WEBUI_APP: Final[Path] = REPO_ROOT / "src" / "Undefined" / "webui" / "app.py"
WEBUI_TEMPLATE: Final[Path] = (
    REPO_ROOT / "src" / "Undefined" / "webui" / "templates" / "index.html"
)


def _script_src(csp: str) -> str:
    """取出 script-src 指令；缺省时按 CSP 规范回退到 default-src。"""
    for directive in csp.split(";"):
        parts = directive.split()
        if parts and parts[0] == "script-src":
            return " ".join(parts[1:])
    return ""


def _webui_csp_template() -> str:
    """从 app.py 里取出 CSP 模板字符串（含 {nonce} 占位符）。"""
    text = WEBUI_APP.read_text(encoding="utf-8")
    match = re.search(r'"([^"]*script-src[^"]*)"', text)
    assert match, "未在 webui/app.py 中找到 CSP 字符串"
    return match.group(1)


def test_tauri_csp_forbids_inline_and_eval_scripts() -> None:
    """Tauri 端 CSP：脚本只允许 self，不得出现 unsafe-inline / unsafe-eval。"""
    conf = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    csp = str(conf["app"]["security"]["csp"])
    script_src = _script_src(csp)

    assert script_src, f"缺少 script-src：{csp}"
    assert "'self'" in script_src, script_src
    assert "unsafe-inline" not in script_src, script_src
    assert "unsafe-eval" not in csp, csp


def test_webui_csp_uses_nonce_and_forbids_eval() -> None:
    """WebUI 端 CSP：脚本走 nonce，不得出现 unsafe-inline / unsafe-eval。"""
    csp = _webui_csp_template()
    script_src = _script_src(csp)

    assert "'self'" in script_src, script_src
    assert "nonce-{nonce}" in script_src or "nonce-" in script_src, script_src
    assert "unsafe-inline" not in script_src, script_src
    assert "unsafe-eval" not in csp, csp


def test_webui_template_declares_nonce_placeholders() -> None:
    """模板里的内联脚本必须带 nonce 占位符，否则在 nonce CSP 下会被拦。"""
    html = WEBUI_TEMPLATE.read_text(encoding="utf-8")
    inline_scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    assert inline_scripts, "模板里应存在内联 script"
    for tag in inline_scripts:
        assert "nonce=" in tag, f"内联 script 缺少 nonce：{tag}"
