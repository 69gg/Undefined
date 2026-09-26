"""WebUI 样式与模板契约（解析式断言）。

取代原先在 ``tests/test_webui_runtime_chat_frontend.py`` 里对 CSS 原文做
`assert "min-width: 0;" in css` 的写法：那种断言改个格式就红，而真正的样式回归
（规则被删、值被换）未必测得到。

这里用 ``tests/webui_css_helpers.py`` 的最小 CSS 解析器，按**选择器**取出声明块，
再断言解析得到的属性值。不模拟层叠与优先级（那是浏览器的事），只表达
「这条规则里必须有这个属性且值正确」。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final

from webui_css_helpers import Stylesheet

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
TEMPLATE: Final[Path] = (
    REPO_ROOT / "src" / "Undefined" / "webui" / "templates" / "index.html"
)
LOG_VIEW_JS: Final[Path] = (
    REPO_ROOT / "src" / "Undefined" / "webui" / "static" / "js" / "log-view.js"
)


# --------------------------------------------------------------------------- #
# 工具块状态配色
# --------------------------------------------------------------------------- #


def test_tool_status_colors_drive_left_bar_and_status_text() -> None:
    """左侧色条走 --tool-accent，各状态文字颜色分别由对应规则给出。

    只断言 `--tool-accent: var(--success);` 这类原文子串是不够的——真正要守的是
    「色条引用该变量」+「每个状态都有各自的文字颜色」这层关系。
    """
    css = Stylesheet.load("components.css")

    # 色条引用 accent 变量
    bar = css.declarations(".runtime-tool-block::before")
    assert bar.get("background") == "var(--tool-accent)", bar

    # 运行中/成功/失败/取消各有自己的 accent 或文字色
    running = css.declarations(".runtime-tool-block.running")
    assert "warning" in running.get("--tool-accent", ""), running

    status_colors = {
        ".runtime-tool-block.running summary .runtime-tool-status": "var(--warning)",
        ".runtime-tool-block.done summary .runtime-tool-status": "var(--success)",
        ".runtime-tool-block.error summary .runtime-tool-status": "var(--error)",
        ".runtime-tool-block.cancelled summary .runtime-tool-status": "var(--warning)",
    }
    for selector, expected in status_colors.items():
        actual = css.declarations(selector).get("color")
        assert actual == expected, (
            f"{selector} 的 color 应为 {expected}，实际 {actual!r}"
        )

    # 中性状态文字色必须与「有结论」的状态区分开
    neutral = css.declarations(".runtime-tool-block summary .runtime-tool-status")
    assert neutral.get("color") == "var(--text-tertiary)", neutral


# --------------------------------------------------------------------------- #
# 移动端工具行不溢出
# --------------------------------------------------------------------------- #


def test_mobile_tool_rows_have_overflow_guards() -> None:
    """窄屏下工具行的名称/耗时/状态必须可截断，且摘要用网格分配宽度。"""
    css = Stylesheet.load("components.css")

    # 可变宽度的部件必须可收缩 + 省略号
    for selector in (
        ".runtime-tool-block summary .runtime-tool-name",
        ".runtime-tool-block summary .runtime-tool-status",
    ):
        declarations = css.declarations(selector)
        assert declarations.get("min-width") == "0", declarations
        assert declarations.get("overflow") == "hidden", declarations
        assert declarations.get("text-overflow") == "ellipsis", declarations
        assert declarations.get("white-space") == "nowrap", declarations

    # 类型标签有固定下限，不能被挤没
    kind = css.declarations(".runtime-tool-block summary .runtime-tool-kind")
    assert kind.get("min-width") == "44px", kind
    assert kind.get("text-overflow") == "ellipsis", kind

    # 耗时不允许被压缩掉（窄屏下它最容易先消失）
    duration = css.declarations(".runtime-tool-block summary .runtime-tool-duration")
    assert duration.get("flex") == "0 0 auto", duration

    # 摘要用网格分配宽度：名称可收缩、耗时/状态下限固定
    summary = css.declarations(".runtime-tool-block summary")
    assert summary.get("display") == "grid", summary
    columns = summary.get("grid-template-columns", "")
    assert "minmax(0, 1fr)" in columns, columns

    # 结构化预览行有明确的最小标签宽度，避免长键名挤掉内容
    structured = css.declarations(".runtime-tool-structured-row")
    assert structured.get("grid-template-columns", "").startswith("minmax(64px"), (
        structured
    )


# --------------------------------------------------------------------------- #
# 长内容不产生横向滚动
# --------------------------------------------------------------------------- #


def test_content_wraps_long_code_and_markdown_without_horizontal_scroll() -> None:
    """代码块与 Markdown 内容要能换行/收缩，容器不得出现横向溢出。"""
    css = Stylesheet.load("components.css")

    # 找到承载长内容的规则：必须同时具备收缩与换行约束
    candidates = [
        declarations
        for declarations in css.declarations_matching("runtime-code-block")
        + css.declarations_matching("runtime-chat-content")
        + css.declarations_matching("runtime-chat-markdown")
    ]
    assert candidates, "未找到代码块/内容容器的样式规则"

    def has(prop: str, value: str) -> bool:
        return any(decl.get(prop) == value for decl in candidates)

    assert has("max-width", "100%") or has("min-width", "0"), (
        "长内容容器缺少收缩约束（min-width: 0 或 max-width: 100%）"
    )

    all_declarations = [
        declarations
        for _, declarations in css._rules  # noqa: SLF001 - 需要跨选择器查属性
    ]
    wrap_values = {
        decl.get("overflow-wrap")
        for decl in all_declarations
        if decl.get("overflow-wrap")
    }
    assert "anywhere" in wrap_values or "break-word" in wrap_values, wrap_values


# --------------------------------------------------------------------------- #
# 聊天布局：输入固定底部、日志可滚
# --------------------------------------------------------------------------- #


def _grid_rows(css: Stylesheet, selector: str) -> str:
    return css.declarations(selector).get("grid-template-rows", "")


def test_chat_layout_keeps_input_at_bottom_and_log_scrollable() -> None:
    """聊天页必须是「固定视口高度 + 中间行可收缩」的网格，输入行不能脱离文档流。"""
    app = Stylesheet.load("app.css")

    layout = app.declarations(".main-content.chat-layout")
    assert layout.get("display") == "flex", layout
    assert layout.get("height") == "100dvh", layout
    assert layout.get("overflow") == "hidden", layout
    assert layout.get("min-height") == "0", layout

    # 中间区域可收缩，否则日志会撑破布局而不是滚动
    chat_tab = app.declarations(".main-content.chat-layout #tab-chat.active")
    rows = chat_tab.get("grid-template-rows", "")
    assert rows.startswith("auto"), rows
    assert "minmax(0, 1fr)" in rows, rows

    # 输入行保持常规流（不用 fixed/sticky），避免遮挡日志
    input_rules = [
        declarations
        for selector, declarations in app._rules  # noqa: SLF001
        if "runtime-chat-input" in selector
    ]
    assert input_rules, "未找到聊天输入行的样式"
    for declarations in input_rules:
        assert declarations.get("position") not in ("fixed", "sticky"), declarations


# --------------------------------------------------------------------------- #
# 模板结构契约（解析 HTML 的 id/inline script nonce）
# --------------------------------------------------------------------------- #


def test_chat_template_declares_required_widgets() -> None:
    """模板必须提供聊天区依赖的关键节点（id 列表来自 runtime.js 的 get() 调用）。"""
    html = TEMPLATE.read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    required = {
        "runtimeChatLog",
        "runtimeChatInput",
        "btnRuntimeChatSend",
        "runtimeChatAutoScroll",
        "runtimeChatAttachments",
        "runtimeChatReferences",
        "runtimeChatConversations",
        "runtimeChatCommandPalette",
        "runtimeChatImageViewer",
        "runtimeHtmlRunner",
        "runtimeHtmlRunnerFrame",
    }
    missing = sorted(required - ids)
    assert not missing, f"模板缺少聊天区必需节点：{missing}"


def test_html_preview_iframe_has_sandbox() -> None:
    """HTML 预览 iframe 必须声明 sandbox（隔离的前提）。"""
    html = TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r"<iframe[^>]*id=\"runtimeHtmlRunnerFrame\"[^>]*>", html)
    assert match, "模板缺少 HTML 预览 iframe"
    sandbox = re.search(r'sandbox="([^"]*)"', match.group(0))
    assert sandbox, f"iframe 未声明 sandbox：{match.group(0)}"
    assert "allow-scripts" in sandbox.group(1), sandbox.group(1)
    assert "allow-same-origin" not in sandbox.group(1), sandbox.group(1)


# --------------------------------------------------------------------------- #
# 日志加载行数（解析 JS 常量与其使用点）
# --------------------------------------------------------------------------- #


def test_logs_fetch_more_tail_lines_by_default() -> None:
    """日志默认拉取的尾部行数应由常量统一给出，且不得残留旧的 200 字面量。"""
    source = LOG_VIEW_JS.read_text(encoding="utf-8")

    constant = re.search(r"const\s+LOG_TAIL_LINES\s*=\s*(\d+)\s*;", source)
    assert constant, "缺少 LOG_TAIL_LINES 常量"
    assert int(constant.group(1)) >= 1000, constant.group(1)

    # 使用点必须引用常量而不是硬编码旧值
    assert re.search(r"lines:\s*String\(LOG_TAIL_LINES\)", source), "未按常量传 lines"
    assert not re.search(r"lines:\s*\"200\"", source), "仍存在硬编码的 200"


def test_tauri_window_config_is_parsable() -> None:
    """占位：确保 tauri 配置仍是合法 JSON（其它契约由 CSP 测试覆盖）。"""
    conf = REPO_ROOT / "apps" / "undefined-console" / "src-tauri" / "tauri.conf.json"
    data = json.loads(conf.read_text(encoding="utf-8"))
    assert "app" in data


# --------------------------------------------------------------------------- #
# 已知不可达：jsdom 下的滚动位置契约
# --------------------------------------------------------------------------- #


def test_scroll_position_contracts_are_blocked_by_jsdom_limitations() -> None:
    """记录三条**当前无法行为化**的滚动契约（附证据与解除条件）。

    它们原先靠对 runtime.js 做源码子串匹配来"覆盖"。迁移时实测结论如下，
    因此改为在这里显式登记，而不是继续留着会误导人的子串断言：

    1. **惰性加载的位置补偿**（`loadOlderChatHistory` 里的
       `log.scrollTop = previousTop + (scrollHeight - previousHeight)`）：
       jsdom 没有布局引擎，`scrollHeight` 恒为 0，补偿量恒为 0，无法区分
       "补偿正确" 与 "没补偿"。虽然可以给 `scrollHeight` 打桩，但补偿值的推导
       依赖真实高度变化，桩出来的数字只能验证算术、验证不了行为。
    2. **tab 激活强制滚到底**：`onTabActivated` 首行是
       `if (!state.authenticated) return;`，而认证态由登录流程设置。可驱动，
       但要么伪造 `window.state.authenticated`（改全局状态，遮蔽真实鉴权路径），
       要么走完整登录流程；两者都不适合放在静态前端测试里。
    3. **惰性加载的触发条件**：`chatLog` 的 scroll 监听先判
       `isChatTopHistoryLoadSuppressed()`，该抑制窗由"滚到底"设置（900ms）。
       实测直接派发 scroll 事件时抑制窗仍在，请求不会发出——这是**正确行为**，
       但使该路径在 jsdom 里不可稳定复现。

    已行为化的部分见 `tests/test_webui_runtime_chat_behavior.py` 的
    `test_send_message_scrolls_chat_to_bottom`（发送后确实触发滚动）。

    解除条件：引入真实布局环境（Playwright / 浏览器 runner）后，把这三条改写为
    端到端断言，并删除本登记。
    """
    # 断言证据仍然成立，避免这条登记悄悄过期
    app = Stylesheet.load("app.css")
    layout = app.declarations(".main-content.chat-layout")
    assert layout.get("overflow") == "hidden", (
        "聊天布局仍依赖内部滚动（overflow: hidden + 内层 overflow-y: auto），"
        "若改为整页滚动请重新评估本登记"
    )
