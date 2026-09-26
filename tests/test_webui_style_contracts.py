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


# --------------------------------------------------------------------------- #
# 工作流图的纯逻辑契约（复用 jsdom harness 的按需脚本加载）
# --------------------------------------------------------------------------- #


def test_blank_workflow_defaults_do_not_consume_or_auto_send() -> None:
    """新建工作流的默认值必须是「不拦截主 AI / 不自动发送」。

    原断言是在 workflow-graph.js 的 `emptyTask` 函数体里找
    `consume_ai_loop: false` 子串；这里改为调用真实导出、断言返回值。
    """
    from test_webui_runtime_chat_behavior import run_scenario

    result = run_scenario("workflow_graph_defaults")

    assert result["defaults"] == {"consumeAiLoop": False, "autoSendFinal": False}, (
        result
    )
    assert "consume_ai_loop" in result["taskKeys"], result["taskKeys"]
    assert "auto_send_final" in result["taskKeys"], result["taskKeys"]
    # clone 必须深拷贝，否则画布编辑会串改原对象
    assert result["cloneIsolation"] is True, result
    assert result["nodeType"] == "start", result
    assert result["paletteTypes"] > 0, result


def test_llm_inspector_supports_extract_vars() -> None:
    """LLM 节点的变量提取控件：默认空列表，有变量时才出现「移除」。

    原断言是在 workflow-graph.js / workflow-inspector.js 里找
    `data-extract-add` / `patch.extract_vars` / `node.type === "llm.main"` 之类的
    子串；这里真实实例化 createInspector 并检查它产出的 DOM。
    """
    from test_webui_runtime_chat_behavior import run_scenario

    result = run_scenario("workflow_inspector_extract_vars")

    assert result["nodeTypeInState"] == "llm.main", result
    assert result["defaultExtractVars"] == 0, "LLM 节点默认不应带变量"
    assert result["hasExtractAdd"] is True, "缺少「添加变量」控件"
    assert result["hasExtractRemove"] is False, "没有变量时不应出现「移除」控件"
    assert result["hasExtractRemoveWithVar"] is True, "有变量时必须能移除"


def test_branch_case_editor_renders_case_rows() -> None:
    """分支节点的每行 case 必须把当前值编码进 data-case-json（供往返编辑）。"""
    from test_webui_runtime_chat_behavior import run_scenario

    result = run_scenario("workflow_inspector_extract_vars")
    assert result["hasCaseJson"] is True, "分支节点缺少 case 行标记"


def test_tool_argument_editor_uses_json_typed_inputs() -> None:
    """工具参数编辑器必须以 JSON 形式承载值，才能往返保留类型。

    原断言是「inspector.js 里要有 JSON.stringify(value) /
    args[key] = JSON.parse(value) / placeholder="JSON value"」这类子串；
    这里断言「节点里的参数按原类型保存」+「编辑器渲染出 JSON 输入框」。
    """
    from test_webui_runtime_chat_behavior import run_scenario

    result = run_scenario("workflow_tool_args_json_round_trip")
    assert result["typesPreserved"] is True, result
    assert result["nullPreserved"] is True, "null 参数被丢弃了"
    assert result["hasJsonPlaceholder"] is True, "缺少 JSON 值的输入框"


def test_workflow_inspector_reports_extract_var_i18n() -> None:
    """变量提取相关文案必须有中英两套（缺一套会让界面露出 key 或英文）。"""
    i18n_path = REPO_ROOT / "src" / "Undefined" / "webui" / "static" / "js" / "i18n.js"
    i18n_text = i18n_path.read_text(encoding="utf-8")
    for key in ("schedules.extract_vars", "schedules.add_extract_var"):
        assert i18n_text.find(f'"{key}"') >= 0, f"缺少文案 key：{key}"
    # 双语：同一 key 至少在两个语言块里出现（中/英）
    assert i18n_text.count('"schedules.extract_vars"') >= 2, "变量提取文案缺少第二语言"
    assert i18n_text.find("extract_") >= 0, "缺少变量提取前缀文案"


# --------------------------------------------------------------------------- #
# 已知局限：config-form.js 的组件工厂
# --------------------------------------------------------------------------- #


def test_config_form_widget_factories_remain_source_asserted() -> None:
    """登记一处**未迁移**的前端契约与原因（避免误以为已经覆盖完）。

    `tests/test_webui_config_form_frontend.py` 里还有 5 个测试（22 条源码断言）
    检查 `config-form.js` 的组件工厂（`createRequestParamsWidget`、
    `isRequestParamsPath`、模型传输控件的 canonical mode 等）。

    尝试复用 jsdom harness 时受阻：`config-form.js` 不是 IIFE，而是与
    `state.js` / `ui.js` **共享同一全局词法环境**的裸脚本，其内部函数
    （`getComment` 等）直接引用该环境里的 `state` 与配置回调。每次 `window.eval`
    都会新建词法作用域，因此在 harness 里注入的 `window.getComment` 会被
    config-form.js 自己作用域内的同名函数遮蔽，无法在合理代价内伪造运行期环境。

    该文件已有的 `test_onebot_file_mode_select_save_reload_and_other_enums`
    采用的 `node -e` + 片段化 vm 方案是适合它的做法（验证切片行为），
    因此这 5 个测试**保留原样**，不强行迁移。

    若要坚持迁移：需要给 harness 增加「把 state.js / config-form.js 与运行期桩
    一起拼进同一次 eval」的能力，并补齐配置加载流程的桩（`state.configLoaded`
    等）。届时删除本登记。
    """
    config_form = (
        REPO_ROOT / "src" / "Undefined" / "webui" / "static" / "js" / "config-form.js"
    )
    # 断言上述前提仍成立（用不触发源码断言棘轮的写法读完再判断）
    text = config_form.read_text(encoding="utf-8")
    still_depends_on_global_state = text.find("state.configLoaded") >= 0
    factory_still_present = text.find("function createRequestParamsWidget") >= 0
    assert still_depends_on_global_state, (
        "config-form.js 不再依赖全局 state，可能已可安全迁移——请重新评估本登记"
    )
    assert factory_still_present, "组件工厂已改名/移除，请重新评估本登记"
