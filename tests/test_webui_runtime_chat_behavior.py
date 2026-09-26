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


def test_active_job_lookup_is_scoped_to_conversation() -> None:
    """恢复活跃作业时必须按会话查询，避免把别的会话的作业挂到当前会话。"""
    result = run_scenario("requests_carry_conversation_id")
    active = [url for url in result["requests"] if "/chat/jobs/active" in url]
    assert active, result["requests"]
    assert all("conversation_id=conv-9" in url for url in active), active
