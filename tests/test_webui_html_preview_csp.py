"""HTML 预览的 CSP 契约（配置级断言，不是源码子串匹配）。

原断言把整份 webui/app.py 与 tauri.conf.json 当字符串读，再找
`"script-src 'self' 'nonce-{nonce}'; "` 这类子串——配置文件改一个字就红，
而真正的安全回归（有人加了 unsafe-inline / unsafe-eval）却未必测得到。
这里改为解析 CSP 字符串本身，逐条指令断言。
"""

from __future__ import annotations

import ast
import json
from html.parser import HTMLParser
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

#: CSP 里唯一允许的脚本来源（nonce 由 WebUI 自己再加一条）。
_ALLOWED_SCRIPT_SOURCE: Final[str] = "self"


def _effective_script_directives(csp: str) -> dict[str, list[str]]:
    """生效的脚本指令：``script-src``（缺省按规范回退 ``default-src``）与 ``script-src-elem``。

    只读 ``script-src`` 不够：``script-src-elem`` **覆盖**它对 ``<script>`` 元素的
    约束，单独写一条 ``script-src-elem 'unsafe-inline'`` 就能放开脚本策略，而
    ``script-src`` 看上去依然干净。来源 token 去掉外层引号（``'self'`` → ``self``），
    便于按集合精确比较。
    """
    directives: dict[str, list[str]] = {}
    for directive in csp.split(";"):
        parts = directive.split()
        if not parts:
            continue
        name = parts[0].lower()
        if name not in directives:
            directives[name] = [source.strip("'") for source in parts[1:]]

    script_src = directives.get("script-src")
    if script_src is None:
        script_src = directives.get("default-src", [])
    effective = {"script-src": script_src}
    if "script-src-elem" in directives:
        effective["script-src-elem"] = directives["script-src-elem"]
    return effective


def _webui_csp_policy() -> str:
    """从 app.py 取出生效的 ``CSP_POLICY`` 常量（含 ``{nonce}`` 占位符）。

    静态求值而不是正则匹配字符串字面量：``CSP_POLICY`` 是**多段隐式拼接**的，
    只取含 ``script-src`` 的那一段会丢掉 ``default-src`` 与后续片段，于是写在别的
    片段里的 ``script-src-elem`` / ``unsafe-eval`` 完全测不到。CPython 会把相邻
    字面量折叠成一个 ``Constant``，所以 AST 上的取值就是完整策略。
    """
    tree = ast.parse(WEBUI_APP.read_text(encoding="utf-8"))
    found: ast.Constant | None = None
    for node in tree.body:  # 只看模块顶层：取最后一次赋值（生效的那份）
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        names = (
            [target.id for target in node.targets if isinstance(target, ast.Name)]
            if isinstance(node, ast.Assign)
            else ([node.target.id] if isinstance(node.target, ast.Name) else [])
        )
        if "CSP_POLICY" in names:
            assert isinstance(node.value, ast.Constant), (
                "app.py 的 CSP_POLICY 不再是常量字符串，无法静态求值；"
                "请更新本测试的提取方式（不要退回正则扫原文）"
            )
            found = node.value
    assert found is not None, "未在 webui/app.py 中找到模块级 CSP_POLICY"
    assert isinstance(found.value, str), found
    return found.value


class _ScriptTagCollector(HTMLParser):
    """收集 ``<script>`` 开始标签的属性。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.tags.append(dict(attrs))


def _script_tags(html: str) -> list[dict[str, str | None]]:
    """按 HTML 规则解析 ``<script>`` 标签并取属性。

    不能用正则扫原文：``(?![^>]*\\bsrc=)`` 会把 ``data-src=`` 也当成外部脚本
    （``-`` 与 ``s`` 之间就是词边界），于是一个内联脚本只要带上 ``data-src`` 就
    绕过了「必须有 nonce」的契约；``[^>]*`` 也处理不了引号里的 ``>``。
    """
    collector = _ScriptTagCollector()
    collector.feed(html)
    collector.close()
    return collector.tags


def test_tauri_csp_forbids_inline_and_eval_scripts() -> None:
    """Tauri 端 CSP：脚本只允许 self，不得出现 unsafe-inline / unsafe-eval。"""
    conf = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    csp = str(conf["app"]["security"]["csp"])

    directives = _effective_script_directives(csp)
    assert directives["script-src"], f"缺少 script-src 且无 default-src 回退：{csp}"
    # 精确比较而不是 `in`：`'self' https://cdn.example` 这类放开必须直接变红
    for name, sources in directives.items():
        assert set(sources) == {_ALLOWED_SCRIPT_SOURCE}, (
            f"{name} 只允许 {_ALLOWED_SCRIPT_SOURCE}，实际 {sources}"
        )
    # 整串检查 unsafe-eval（任何指令里都不该出现）；unsafe-inline 只能逐条脚本指令
    # 检查——style-src 合法地带着它。
    assert "unsafe-eval" not in csp, csp


def test_webui_csp_uses_nonce_and_forbids_eval() -> None:
    """WebUI 端 CSP：脚本走 nonce，不得出现 unsafe-inline / unsafe-eval。"""
    csp = _webui_csp_policy()
    directives = _effective_script_directives(csp)
    script_src = directives["script-src"]

    assert _ALLOWED_SCRIPT_SOURCE in script_src, script_src
    assert any(source.startswith("nonce-") for source in script_src), script_src
    # 逐条生效指令检查：整串 `"unsafe-inline" not in csp` 是不成立的
    # （style-src 合法地带着 unsafe-inline），所以必须只盯脚本指令
    for name, sources in directives.items():
        forbidden = [
            source
            for source in sources
            if source in ("unsafe-inline", "unsafe-eval", "unsafe-hashes")
        ]
        assert not forbidden, f"{name} 不得允许 {forbidden}：{sources}"
    assert "unsafe-eval" not in csp, csp


def test_webui_template_declares_nonce_placeholders() -> None:
    """模板里的**内联**脚本必须带 nonce 占位符，否则在 nonce CSP 下会被拦。"""
    tags = _script_tags(WEBUI_TEMPLATE.read_text(encoding="utf-8"))
    assert tags, "模板里应存在 <script> 标签"
    # 只有真正的 src 属性算外部脚本；内联脚本一个都不能漏
    inline = [tag for tag in tags if not tag.get("src")]
    assert inline, "模板里应存在内联 script"
    for tag in inline:
        assert tag.get("nonce"), f"内联 script 缺少 nonce：{tag}"
