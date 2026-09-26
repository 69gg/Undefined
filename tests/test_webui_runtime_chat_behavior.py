"""WebUI 运行时聊天前端的行为测试（jsdom 驱动真实 DOM）。

取代原先在 ``tests/test_webui_runtime_chat_frontend.py`` 里对 ``runtime.js``
源码做子串匹配的写法：那些断言属于变更检测器——重构必然变红，真正的行为回归
却测不出来（见 ``tests/test_source_assertion_budget.py``）。

做法：``tests/frontend/runtime_chat_harness.js`` 用 jsdom 载入真实模板
``index.html``、按模板顺序 eval 真实依赖 JS（含 vendor 的 marked / highlight）
与 ``runtime.js``，再通过受控的 ``window.fetch`` 喂入会话 / 历史 / 作业事件载荷，
用真实 DOM 事件驱动交互；本文件只负责发起场景并断言其结构化快照。

依赖准备：``cd tests/frontend && npm ci``（CI 里已接入）。缺 node 或 jsdom 时跳过。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
HARNESS: Final[Path] = REPO_ROOT / "tests" / "frontend" / "runtime_chat_harness.js"
JSDOM_DIR: Final[Path] = REPO_ROOT / "tests" / "frontend" / "node_modules" / "jsdom"
HARNESS_TIMEOUT_SECONDS: Final[int] = 120

#: CI 上把「依赖缺失」与「harness 文件缺失」当失败：静默 skip 等于没有测试。
#: 本批迁移已删除对应的源码子串断言，一旦这里 skip，覆盖就是 0。
_CI_ENV_VARS: Final[tuple[str, ...]] = ("CI", "GITHUB_ACTIONS")


def _in_ci() -> bool:
    return any(os.environ.get(name) for name in _CI_ENV_VARS)


def _require_env() -> None:
    """检查 node / harness / jsdom。

    本地缺少依赖时 skip（开发者未必装了 jsdom）；CI 上直接失败，否则
    ``release.yml`` 那种没装 jsdom 的流水线会绿灯通过而实际零覆盖。
    """
    if shutil.which("node") is None:
        _missing("需要 node（含 node 本身的缺失）")
    if not HARNESS.is_file():
        _missing(f"缺少 harness：{HARNESS}")
    if not JSDOM_DIR.is_dir():
        _missing("需要 jsdom：cd tests/frontend && npm ci")


def _missing(reason: str) -> None:
    if _in_ci():
        pytest.fail(f"CI 上不得跳过前端行为测试：{reason}")
    pytest.skip(reason)


def run_scenario(scenario: str) -> dict[str, Any]:
    """跑一个 harness 场景，返回其 ``result`` 快照。"""
    _require_env()

    completed = subprocess.run(
        ["node", str(HARNESS), "--scenario", scenario, "--root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=HARNESS_TIMEOUT_SECONDS,
        check=False,
    )
    payload = completed.stdout.strip().splitlines()
    assert payload, f"harness 无输出；stderr={completed.stderr[-2000:]}"
    try:
        data = json.loads(payload[-1])
    except json.JSONDecodeError as exc:  # pragma: no cover - harness 崩溃时给出原始输出
        raise AssertionError(
            f"harness 输出不是 JSON：{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}"
        ) from exc

    if not data.get("ok"):
        raise AssertionError(f"harness 场景 {scenario} 失败：{data.get('error', '')}")
    result = data.get("result")
    assert isinstance(result, dict), f"场景 {scenario} 未返回结构化结果"
    return result


def _bot_nodes(result: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = result.get("allNodes") or result.get("botNodes") or []
    return [node for node in nodes if node.get("role") == "bot"]


def _user_nodes(result: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = result.get("allNodes") or []
    return [node for node in nodes if node.get("role") == "user"]


# --------------------------------------------------------------------------- #
# 消息节点复用
# --------------------------------------------------------------------------- #


def test_final_message_reuses_streaming_node() -> None:
    """连续 message 事件必须复用同一个机器人节点，而不是各追加一条。

    这是「流式占位节点 → 最终消息」的核心行为：早期实现会在 message 事件里
    再 append 一条机器人消息，导致同一轮回复出现两个节点。
    """
    result = run_scenario("message_reuses_streaming_node")

    bots = _bot_nodes(result)
    assert len(bots) == 1, f"机器人消息节点应只有一个，实际 {len(bots)}：{bots}"
    # 两条 message 事件按序进入同一节点的 timeline
    assert bots[0]["contentTexts"] == ["你好", "你好世界"]
    assert bots[0]["messageId"], "流式节点应带 message_id 以便后续复用定位"
    # 用户消息仍然只有一条（发送时写入，不被事件流重复添加）
    assert [node["contentTexts"] for node in _user_nodes(result)] == [["hi"]]


# --------------------------------------------------------------------------- #
# 工具生命周期
# --------------------------------------------------------------------------- #


def test_tool_lifecycle_renders_tool_block() -> None:
    """tool_start / tool_end 应产生一个工具块，并带成功状态与耗时。"""
    result = run_scenario("tool_lifecycle_renders_blocks")

    bots = _bot_nodes(result)
    assert len(bots) == 1
    blocks = bots[0]["toolBlocks"]
    assert len(blocks) == 1, f"应渲染一个工具块，实际 {blocks}"
    block = blocks[0]
    assert "is-tool" in block["classes"]
    # 后端契约是 done/error（不是 "ok"），状态必须反映到工具块上
    assert "done" in block["classes"], f"tool_end 的 status 应反映到工具块：{block}"
    assert "error" not in block["classes"]
    # tool_start 时 autoOpen，成功路径下应保持展开
    assert block["open"] is True
    assert "group.get_member_info" in block["text"]
    # 结果预览应进入工具块文本（避免断言过松以致丢掉预览也通过）
    assert "张三" in block["text"]


def test_tool_duration_survives_done_event() -> None:
    """done 之后工具块必须保留最终耗时，而不是被清空。"""
    result = run_scenario("keeps_duration_after_done")

    blocks = _bot_nodes(result)[0]["toolBlocks"]
    assert len(blocks) == 1
    # 后端给出 2500ms，界面按 2.5s 展示
    assert "2.5s" in blocks[0]["text"], blocks[0]["text"]


# --------------------------------------------------------------------------- #
# stage（实时阶段提示）
# --------------------------------------------------------------------------- #


def test_stage_event_renders_live_stage() -> None:
    """stage 事件应写进机器人节点里的阶段元素，并带上耗时。"""
    result = run_scenario("stage_event_renders_live_stage")

    bots = _bot_nodes(result)
    assert len(bots) == 1
    stage_text = bots[0]["stageText"]
    assert stage_text, "stage 事件后阶段元素不应为空"
    # 阶段文案含「后端 elapsed + 本地流逝」的实时计数，断言具体毫秒数会 flaky；
    # 改为断言 payload 直接决定的稳定量（dataset 由 setChatStage 写自 payload）。
    assert bots[0]["stageBaseMs"] == "500", bots[0]
    assert re.match(r"^.+ · \d+(ms|s)$", stage_text), stage_text
    assert bots[0]["stageHidden"] is False, "有阶段内容时不应保持隐藏"


# --------------------------------------------------------------------------- #
# 渲染消毒（真喂载荷，而不是断言源码里有没有消毒函数）
# --------------------------------------------------------------------------- #


def test_markdown_rendering_sanitizes_unsafe_content() -> None:
    """脚本、内联事件处理器与 javascript: 链接都不得落到 DOM 上。

    原测试断言的是「源码里必须出现 createSafeMarkedRenderer / SAFE_HTML_TAGS /
    name.startsWith("on")」等子串——重构即红，真正的 XSS 回归却测不出来。
    这里把载荷真渲染出来，直接观察结果。

    刻意**不**断言 ``window.__XSS__``：harness 用 ``runScripts: "outside-only"``
    载入 jsdom，注入的 ``<script>`` 永远不会执行，这个值恒为 undefined，
    是一条永远为真的装饰性断言。
    """
    result = run_scenario("markdown_sanitizes_unsafe_content")

    assert result["scriptTags"] == 0, "渲染结果里出现了 script 标签"
    assert result["inlineHandlerAttrs"] == 0, "渲染结果里残留了内联事件处理器"

    hrefs = [anchor["href"] for anchor in result["anchors"]]
    assert not [href for href in hrefs if href.lower().startswith("javascript:")], hrefs
    # 安全外链保留，并带 rel=noreferrer
    safe = [a for a in result["anchors"] if a["href"] == "https://example.com/page"]
    assert safe and safe[0]["rel"] == "noreferrer", result["anchors"]


def test_markdown_and_html_images_are_lazy_and_clickable() -> None:
    """图片要带 loading=lazy 且可点击打开预览（统一走 chatImageMarkup）。"""
    result = run_scenario("markdown_sanitizes_unsafe_content")

    assert result["images"], "未渲染出任何图片"
    for image in result["images"]:
        assert image["loading"] == "lazy", image
    assert result["interactiveImages"] >= 2, (
        f"Markdown 图片与 HTML 图片都应可点击预览：{result['interactiveImages']}"
    )


# --------------------------------------------------------------------------- #
# 滚动行为
# --------------------------------------------------------------------------- #


def test_send_message_scrolls_chat_to_bottom() -> None:
    """发送消息后必须触发滚动到底（含布局更新后的补滚）。

    原断言是「源码里要有 requestAnimationFrame(forceScrollChatToBottom) /
    setTimeout(forceScrollChatToBottom, 80)」这类子串；这里观察真实滚动调用次数。
    """
    result = run_scenario("scroll_behaviors")

    assert result["sendScrolls"] >= 1, result
    # 消息也确实渲染出来了（滚动不是空转）
    bots = _bot_nodes(result)
    assert bots and bots[-1]["contentTexts"], bots


def test_tab_activation_scrolls_chat_to_bottom() -> None:
    """切回聊天 tab 要强制滚到底。

    这条以前没有任何断言，实测恒为 0：``onTabActivated`` 有
    ``if (!state.authenticated) return`` 前置守卫，harness 里登录态是假的，
    调用直接空转。现在 harness 在载入产品脚本时摆好 ``state.authenticated``，
    且第二次激活时历史已加载（``loadChatHistory`` 早退），所以计到的滚动
    只能来自 ``onTabActivated`` 自己。
    """
    result = run_scenario("scroll_behaviors")

    assert result["tabActivationScrolls"] >= 1, result


def test_lazy_loading_older_history_keeps_viewport_position() -> None:
    """滚到顶部要加载更早历史，并用新增高度补偿 scrollTop，保持可视位置。

    这条以前没有任何断言，实测 ``olderHistoryRequestCount == 0``、
    ``lazyLoadScrollTop`` 停在初始值：harness 把 scrollTop 设成 40，
    而触发阈值是 ``<= 32``；而且轮询里的「滚到底」会不停续期 900ms 的
    顶部加载抑制窗口。改法：滚到 0、等作业结束再等过抑制窗口。
    """
    result = run_scenario("scroll_behaviors")

    assert result["olderHistoryRequestCount"] >= 1, result
    # 高度确实增长了，否则「补偿」无从谈起
    assert result["lazyLoadHeight"] > 2000, result
    assert result["lazyLoadScrollTop"] == result["lazyLoadExpectedTop"], result


# --------------------------------------------------------------------------- #
# 工具块：快照去重与自动折叠
# --------------------------------------------------------------------------- #


def test_unchanged_tool_snapshot_does_not_rerender_node() -> None:
    """内容相同的工具快照不得重建 DOM 节点（避免闪烁与展开态丢失）。

    观测窗必须**恰好跨过一次轮询**：两次读取安排在携带相同快照那一轮的前后，
    否则轮询间隔（500ms）远大于随手读两次的间隔，读取必然落在同一轮之后，
    ``sameNodeReused`` 恒真（把 toolRenderSignature 改成随机值也照样绿）。
    """
    result = run_scenario("tool_snapshot_dedup_and_auto_collapse")

    assert result["toolBlockCount"] == 1, result
    assert result["pollsBetweenReads"] == 1, result
    assert result["sameNodeReused"] is True, result


def test_tool_block_auto_collapses_after_minimum_visible_time() -> None:
    """工具结束后经过最小可见时间要自动折叠（去掉 open）。"""
    result = run_scenario("tool_snapshot_dedup_and_auto_collapse")

    assert result["openAfterSnapshot"] is True, "工具块应先展开"
    assert result["openAfterEnd"] is True, "结束时仍在最小可见时间内，应保持展开"
    assert result["openAfterCollapse"] is False, result
    assert "done" in result["classesAfterCollapse"], result["classesAfterCollapse"]


# --------------------------------------------------------------------------- #
# HTML 运行器（沙箱隔离）
# --------------------------------------------------------------------------- #


def test_html_runner_opens_sandboxed_preview() -> None:
    """点「运行 HTML」要打开预览面板，并把带 CSP 的文档注入沙箱 iframe。

    安全要点：iframe 的 sandbox **不得**包含 allow-same-origin（与 allow-scripts
    同时存在会让沙箱形同虚设），且注入的文档必须自带 CSP 与 nonce。
    """
    result = run_scenario("html_runner_uses_sandboxed_preview")

    assert result["runButtonExists"] is True, "HTML 代码块应有运行按钮"
    assert result["hiddenBefore"] is True, "初始应隐藏预览面板"
    assert result["hiddenAfter"] is False, "点击后应打开预览面板"

    sandbox = result["sandbox"]
    assert "allow-scripts" in sandbox, sandbox
    assert "allow-same-origin" not in sandbox, (
        f"sandbox 含 allow-same-origin 会削弱隔离：{sandbox}"
    )
    assert result["srcdocHasCsp"] is True, "注入文档缺少 CSP"
    # nonce 必须挂在真实 <script> 标签上：只搜 /nonce-[A-Za-z0-9]+/ 的话，
    # CSP meta 自己的 'nonce-…' 就能满足它，脚本标签被整个删掉也测不出来。
    assert result["srcdocScriptNonce"], "注入文档里没有带 nonce 的 <script> 标签"
    assert result["srcdocNonceMatchesCsp"] is True, (
        f"CSP 声明的 nonce 与脚本标签上的不一致，等于没有保护：{result}"
    )
    assert result["srcdocHasInlineSource"] is True, "注入文档未包含源内容"


# --------------------------------------------------------------------------- #
# 增量轮询
# --------------------------------------------------------------------------- #


def test_job_events_are_polled_incrementally() -> None:
    """事件轮询必须用 after 游标推进，而不是每轮重放全部事件。

    原断言是「源码里要有 after: String(runtimeState.lastEventSeq)」这类子串；
    这里观察真实请求序列。
    """
    result = run_scenario("incremental_polling_and_resume")

    assert result["eventRequestCount"] >= 3, result
    after_values = result["afterValues"]
    assert after_values[0] == "0", after_values
    # 游标必须严格推进
    numeric = [int(value) for value in after_values]
    assert numeric == sorted(numeric), numeric
    assert numeric[-1] > numeric[0], numeric
    # 两轮事件的内容都要落到同一条机器人消息上
    bots = _bot_nodes(result)
    assert len(bots) == 1, bots
    assert bots[0]["contentTexts"] == ["first", "second"], bots[0]


def test_active_job_is_queried_on_history_load() -> None:
    """刷新后加载历史时应查询活跃作业（用于恢复）。"""
    result = run_scenario("incremental_polling_and_resume")
    assert result["activeJobQueried"] is True, result


# --------------------------------------------------------------------------- #
# 附件粘贴与引用条
# --------------------------------------------------------------------------- #


def test_pasted_file_becomes_pending_attachment() -> None:
    """把文件粘贴进输入框要挂成待发附件（显示文件名与大小）。"""
    result = run_scenario("paste_files_and_quote_reference")

    assert result["pendingAttachments"] >= 1, result
    assert "pasted.txt" in result["attachmentsText"], result["attachmentsText"]


def test_quote_button_prepends_reference() -> None:
    """点机器人消息的「引用」要把该消息作为引用挂上去。"""
    result = run_scenario("paste_files_and_quote_reference")

    assert result["quoteExists"] is True, "机器人消息上应有引用按钮"
    assert result["referencesCount"] >= 1, result
    text = result["referencesText"]
    assert "引用" in text, text
    assert "机器人历史消息" in text, text


def test_quote_reference_becomes_markdown_prefix_at_send_time() -> None:
    """引用在**发送时**被前置成 markdown 引用块，而不是塞进输入框。

    以前只读了 ``input.value``（引用在独立的引用条里，那里恒为空串），
    等于什么都没验证；真正的契约在 POST /chat/jobs 的 message 上。
    """
    result = run_scenario("paste_files_and_quote_reference")

    message = result["outboundMessage"]
    assert message, result
    quote_block, _, body = message.partition("\n\n")
    assert quote_block.startswith("> "), message
    assert all(line.startswith("> ") for line in quote_block.splitlines()), message
    assert "机器人历史消息" in quote_block, message
    # 用户自己写的内容在引用之后，且不带引用前缀
    assert body.startswith("请继续"), message
    assert not body.startswith("> "), message


# --------------------------------------------------------------------------- #
# UI 控件（会话列表 / 命令面板 / 图片查看器）
# --------------------------------------------------------------------------- #


def test_conversation_list_renders_from_backend() -> None:
    """后端返回的会话要渲染进侧栏列表。"""
    result = run_scenario("ui_controls")
    assert result["conversationItems"] == 2, result["conversationItems"]


def test_conversation_drawer_toggles_on_narrow_viewport() -> None:
    """窄视口下点抽屉开关要真的展开/收起侧栏。

    这条以前没有任何断言，实测恒 False：开关受 ``innerWidth <= 768`` 门控，
    jsdom 默认 1024，点了等于空转；而且 harness 读的还是面板元素，产品把
    ``is-open`` 挂在 ``.runtime-chat-sidebar`` 上。
    """
    result = run_scenario("ui_controls")

    assert result["drawerOpenBefore"] is False, "初始应收起"
    assert result["drawerOpenAfter"] is True, result
    assert result["drawerAriaExpandedAfter"] == "true", result
    assert result["drawerOpenAfterSecondToggle"] is False, "再点一次应收起"


def test_slash_triggers_command_palette() -> None:
    """输入 `/` 要打开命令面板，并列出后端返回的命令条目。

    这条以前只断言「面板不隐藏」：fixture 的路由写成 `/chat/commands`，与产品
    实际请求的 `/api/runtime/commands?scope=webui` 对不上，面板恒为空态，还被
    当成「jsdom 限制」登记成了豁免。路由修正后可以断言真实条目。
    """
    result = run_scenario("ui_controls")

    assert result["paletteHidden"] is False, "输入 / 后命令面板应可见"
    assert result["paletteItems"] == 2, result["paletteText"]
    assert "help" in result["paletteText"], result["paletteText"]
    assert "stats" in result["paletteText"], result["paletteText"]


def test_image_preview_opens_and_closes_viewer() -> None:
    """点可点击预览图要打开查看器并载入该图，关闭按钮要能收起。"""
    result = run_scenario("ui_controls")

    assert result["previewImageCount"] >= 1, result
    assert result["viewerHiddenBefore"] is True, "初始应隐藏"
    assert result["viewerHiddenAfter"] is False, "点击预览图后应打开"
    assert result["viewerImageSrc"] == "https://example.com/pic.png", result
    assert result["viewerHiddenClosed"] is True, "关闭按钮应能收起查看器"


# --------------------------------------------------------------------------- #
# 取消与重试控件
# --------------------------------------------------------------------------- #


def test_cancel_control_targets_the_running_job() -> None:
    """运行中要出现可用的取消按钮，点击后向该作业发出取消请求。"""
    result = run_scenario("cancel_and_retry_controls")

    assert result["cancelButtonCount"] == 1, result
    assert result["visibleCancelCount"] == 1, "运行中取消按钮应可见"
    assert result["cancelJobId"] == "job-cancel", result
    assert result["cancelDisabledBeforeClick"] is False
    assert result["cancelRequested"] is True, result["requests"]


def test_retry_control_reuses_the_user_message() -> None:
    """重试按钮要复用那条用户消息的原文，而不是空内容。"""
    result = run_scenario("cancel_and_retry_controls")

    assert result["retryButtonCount"] == 1, result
    assert result["retryContent"] == "please do it", result["retryContent"]


# --------------------------------------------------------------------------- #
# 富内容渲染（引用块 / 代码高亮 / 独立 HTML / 工具预览 / 附件去重）
# --------------------------------------------------------------------------- #


def test_markdown_quotes_render_as_blockquotes() -> None:
    """Markdown 引用要渲染成 blockquote（而非原样文本）。"""
    result = run_scenario("rich_content_rendering")
    assert result["blockquotes"] == 1, result["blockquotes"]


def test_markdown_code_blocks_are_highlighted() -> None:
    """代码块要过高亮（产出 pre > code 且带 hljs / language- 标记）。"""
    result = run_scenario("rich_content_rendering")
    assert result["preCount"] >= 1, result
    assert result["highlighted"] >= 1, result


def test_standalone_html_is_preserved_as_element() -> None:
    """独立 HTML 必须作为**元素**渲染，而不只是「文本里出现过这几个字」。

    原来只断言 ``innerText.includes("独立 HTML 片段")``：消毒器把标签转义成
    字面量文本后，这串字照样在内层文本里，断言依旧为真。
    """
    result = run_scenario("rich_content_rendering")
    inline = result["standaloneInlineElement"]
    assert inline is not None, result["allNodes"]
    assert inline["tag"] == "div", inline
    assert inline["insidePre"] is False, inline
    assert inline["insideCode"] is False, inline

    document = result["standaloneDocument"]
    assert document is not None, result["allNodes"]
    assert document["hasMarkerElement"] is True, document
    # 整条消息是一份独立 HTML 文档时走 sanitizeHtmlSnippet 分支：
    # 标签之间的裸文本保持为文本节点，不会被 marked 包成 <p>
    assert document["paragraphCount"] == 0, document


def test_tool_previews_render_structured_input_and_output() -> None:
    """工具块要渲染结构化的入参/输出预览，而不是只显示名称。"""
    result = run_scenario("rich_content_rendering")
    assert result["toolPreviewBlocks"] >= 1, result
    assert "PREVIEW_JSON" in result["toolBlockText"], result["toolBlockText"]


def test_attachment_image_is_inlined_once() -> None:
    """`<attachment uid="pic_dup"/>` 要内联成一张预览图，且不重复渲染附件卡片。

    渲染层会把附件 URL 重写成 /api/runtime/chat/attachments/<uid>/preview。
    """
    result = run_scenario("rich_content_rendering")
    assert result["attachmentImages"] == 1, result["attachmentPreviewSrcs"]
    srcs = result["attachmentPreviewSrcs"]
    assert srcs and "pic_dup" in srcs[0], srcs


# --------------------------------------------------------------------------- #
# 历史时间线恢复
# --------------------------------------------------------------------------- #


def test_history_restores_tool_blocks_without_stream_state() -> None:
    """刷新后从后端历史重建工具块（不依赖流式状态）。

    原断言是对 `renderHistoryTimeline` / `historyWebchatEvents` 等函数体的子串匹配，
    历史渲染坏掉也测不出来。
    """
    result = run_scenario("history_timeline_restores_tool_blocks")

    assert result["toolBlockCount"] == 2, result["toolBlocks"]
    texts = [block["text"] for block in result["toolBlocks"]]
    assert any("web_agent" in text and "3.0s" in text for text in texts), texts
    assert any("render.markdown" in text and "800ms" in text for text in texts), texts
    # 结果预览随历史一起恢复
    assert any("AGENT_PREVIEW" in text for text in texts), texts
    assert any("INNER_PREVIEW" in text for text in texts), texts


def test_history_renders_as_event_timeline_with_final_duration() -> None:
    """历史里的 message 事件进入时间线容器，且 webchat.duration_ms 写进 final 阶段。"""
    result = run_scenario("history_timeline_restores_tool_blocks")

    bots = _bot_nodes(result)
    assert len(bots) == 1, bots
    # 时间线容器存在，且历史 message 事件的内容落在里面
    assert result["timelineContainers"] >= 1, result["timelineContainers"]
    assert "时间线内的中间消息" in bots[0]["contentText"], bots[0]
    # 后端给出的时长进入 final 阶段（不依赖流式事件）
    assert bots[0]["stageBaseMs"] == "4200", bots[0]
    assert bots[0]["stageIsFinal"] is True, bots[0]
    assert "4.2s" in bots[0]["stageText"], bots[0]["stageText"]


# --------------------------------------------------------------------------- #
# 工具块摘要的结构与耗时
# --------------------------------------------------------------------------- #


def test_tool_summary_shows_name_duration_status_kind_in_order() -> None:
    """摘要里应依次出现 名称 → 耗时 → 状态 → 类型，且预览内容可见。

    原断言靠「源码里 runtime-tool-name 的下标小于 runtime-tool-duration …」
    来表达顺序，渲染顺序回归时测不出来；这里解析真实 DOM。
    """
    result = run_scenario("tool_summary_order_and_duration")

    assert result["summaryCount"] == 1, result["summaryParts"]
    parts = result["summaryParts"][0]
    assert parts and parts[0] == "runtime-tool-summary-main", parts
    assert "runtime-tool-status" in parts, parts

    text = result["summaryText"][0]
    # 结构化顺序：工具名 → 耗时 → 状态文案 → 类型文案
    name_at = text.index("render.markdown")
    duration_at = text.index("1.2s")
    status_at = text.index("完成")
    kind_at = text.index("工具")
    assert name_at < duration_at < status_at < kind_at, text


def test_tool_result_preview_is_rendered() -> None:
    """工具的 result_preview 必须出现在工具块里（不是只放在 fixture 里）。"""
    result = run_scenario("tool_summary_order_and_duration")

    assert "RESULT_PREVIEW_TOKEN" in result["blockText"], result["blockText"]
    assert result["previewBlocks"] >= 1, result["previewBlocks"]


# --------------------------------------------------------------------------- #
# 自动滚动开关（只断言确定性可达的部分）
# --------------------------------------------------------------------------- #


def test_auto_scroll_toggle_persists_preference() -> None:
    """切换自动滚动后偏好必须落到 localStorage，并在重新载入时被读回。

    不断言「关掉后不再滚动」：jsdom 里多条渲染路径都会触发滚动，实测开关前后
    调用次数只差 3 次，信号强度不足以支撑可靠断言（宁可少测也不写会漏报的断言）。

    「读回」必须是真的重建一次环境：对同一个 key 再 ``getItem`` 一次等于复读
    ``storedPreference``，恒等，证明不了产品会恢复偏好。
    """
    result = run_scenario("auto_scroll_toggle_controls_scrolling")

    assert result["toggleExists"], "模板缺少自动滚动开关"
    assert result["toggleCheckedAfterChange"] is False
    assert result["storedPreference"] == "false", result["storedPreference"]
    assert result["reloadedToggleChecked"] is False, result


# --------------------------------------------------------------------------- #
# 跨会话隔离
# --------------------------------------------------------------------------- #


def test_foreign_conversation_events_are_ignored() -> None:
    """别的会话的事件不得写进当前会话的聊天区。

    runtime.js 里有两道守卫（applyChatEvent 的 eventForCurrentConversation 过滤与
    applyChatEventsPayload 的归属判断），这是「刷新后把别会话作业挂到当前会话」的
    唯一防线；变异掉守卫也应被这条用例抓住。
    """
    result = run_scenario("foreign_conversation_events_are_ignored")

    bots = _bot_nodes(result)
    assert len(bots) == 1, bots
    # 只出现本会话那条事件的内容；异会话事件的正文不得进入任何节点
    assert bots[0]["contentTexts"] == ["MINE"], bots[0]
    rendered = "\n".join(node["text"] for node in (result.get("allNodes") or []))
    assert "INTRUDER" not in rendered, rendered


# --------------------------------------------------------------------------- #
# done 的最终耗时
# --------------------------------------------------------------------------- #


def test_done_event_writes_final_duration_to_stage() -> None:
    """done 事件要把最终耗时写进阶段元素并标记为 final。

    旧断言守的是 finalizeActiveChatMessage；迁移后一度只剩工具块自身的耗时有覆盖，
    done 的收尾逻辑变异掉也不会变红。
    """
    result = run_scenario("done_event_keeps_final_duration")

    bots = _bot_nodes(result)
    assert len(bots) == 1
    assert bots[0]["contentTexts"] == ["answer"]
    # payload 直接决定 base 值（稳定），并进入 final 态
    assert bots[0]["stageBaseMs"] == "3000", bots[0]
    assert bots[0]["stageIsFinal"] is True, bots[0]
    assert "3.0s" in bots[0]["stageText"], bots[0]["stageText"]


# --------------------------------------------------------------------------- #
# agent 生命周期
# --------------------------------------------------------------------------- #


def test_agent_lifecycle_renders_agent_block() -> None:
    """agent_start / agent_end 应渲染成 is-agent 块并带耗时。"""
    result = run_scenario("agent_lifecycle_renders_agent_block")

    blocks = _bot_nodes(result)[0]["toolBlocks"]
    assert len(blocks) == 1, blocks
    assert "is-agent" in blocks[0]["classes"], blocks[0]
    assert "done" in blocks[0]["classes"], blocks[0]
    assert "web_agent" in blocks[0]["text"]
    assert "1.5s" in blocks[0]["text"], blocks[0]["text"]


def test_requests_never_use_sse_transport() -> None:
    """前端通过 JSON 轮询消费作业事件，不得退回 SSE。

    旧断言用 7 条「源码里不得出现 consumeSse / text/event-stream / token_delta」
    的负向子串来表达这件事。迁移后写成「请求的 accept 头不以 text/event-stream
    开头」——产品从不设置 Accept，实测所有请求都是空串，这条恒真。

    真正的信号是两条：事件端点必须显式要求 ``format=json``（走 fetch + JSON
    轮询），且产品全程不构造 ``EventSource``（SSE 长连接不经过 window.fetch，
    只有靠绊线才能观察到）。
    """
    result = run_scenario("requests_carry_conversation_id")

    details = result.get("requestDetails") or []
    assert details, "未捕获到请求明细"
    event_requests = [
        entry for entry in details if "/jobs/job-9/events" in entry["url"]
    ]
    assert event_requests, details
    for entry in event_requests:
        assert "format=json" in entry["url"], entry["url"]
    assert result["eventSourceConstructions"] == 0, (
        f"事件消费退回了 SSE（EventSource 被构造了 "
        f"{result['eventSourceConstructions']} 次）"
    )


# --------------------------------------------------------------------------- #
# 会话隔离
# --------------------------------------------------------------------------- #


def test_requests_carry_conversation_id() -> None:
    """发起作业与轮询事件都必须带上同一个 conversation_id。"""
    result = run_scenario("requests_carry_conversation_id")
    requests = result["requests"]

    history = [url for url in requests if "/chat/history" in url]
    assert history, requests
    assert all("conversation_id=conv-9" in url for url in history), history

    created = [url for url in requests if url.endswith("/chat/jobs")]
    assert created, requests

    events = [url for url in requests if "/jobs/job-9/events" in url]
    assert events, f"应轮询作业事件，实际请求：{requests}"
    assert all("conversation_id=conv-9" in url for url in events), events
    # 增量轮询：带上 after 游标，避免每轮重放全部事件
    assert all("after=" in url for url in events), events


def test_create_job_body_carries_conversation_id() -> None:
    """POST /chat/jobs 的请求体必须带 conversation_id。

    harness 之前只记录 URL、丢掉 fetch 的 options，所以这条契约一直没被测到。
    """
    result = run_scenario("requests_carry_conversation_id")
    body = result["createJobBody"]
    assert isinstance(body, dict), f"未捕获到创建作业的请求体：{body}"
    assert body["conversation_id"] == "conv-9", body
    assert body["message"], body


def test_active_job_lookup_is_scoped_to_conversation() -> None:
    """恢复活跃作业时必须按会话查询，避免把别的会话的作业挂到当前会话。"""
    result = run_scenario("requests_carry_conversation_id")
    active = [url for url in result["requests"] if "/chat/jobs/active" in url]
    assert active, result["requests"]
    assert all("conversation_id=conv-9" in url for url in active), active


def test_streaming_does_not_fight_the_user_reading_history() -> None:
    """作业还在流式输出时，用户往上翻历史不能被抢滚动条、也不能翻不上去。

    覆盖两个独立缺陷（各自有能单独打红它的变异）：

    - 自动滚动只看 ``chatAutoScroll`` 偏好、不看用户当前位置：流式内容每 500ms
      追加一次就抢一次滚动位置。去掉「钉住底部」的闸后，本用例的
      ``scrollCallsAfterUserScroll`` 会从 0 变成 2。
    - 顶部加载抑制窗口（900ms）会被内容变化持续续期，而 ``loadOlderChatHistory``
      全文件只有 scroll 监听这一个调用点、没有可点的兜底入口，于是用户**无声地
      翻不上去**。去掉「用户上翻即解除抑制」后，
      ``olderHistoryRequestsWhileStreaming`` 会从 1 变成 0。
    """
    result = run_scenario("scroll_while_streaming")

    # 前提：作业确实还在轮询，否则测的就不是「流式期间」
    assert result["jobStillStreaming"], result
    assert result["eventsRequests"] >= 3, result

    # 用户上翻之后不得再被自动滚动拽回底部
    assert result["scrollCallsAfterUserScroll"] == 0, result
    # 并且必须真的发出更早历史的请求
    assert result["olderHistoryRequestsWhileStreaming"] >= 1, result
