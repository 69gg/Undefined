"""配置表单通过真实控件保存时的请求顺序和状态回归。"""

from __future__ import annotations

from typing import Any

import pytest

from test_webui_runtime_chat_behavior import run_scenario


@pytest.mark.parametrize("outcome", ["success", "network_error", "api_error"])
def test_auto_save_serializes_and_coalesces_latest_snapshot(outcome: str) -> None:
    result = run_scenario(f"config_autosave_{outcome}")
    assert result["beforeOldResponse"]["requestCount"] == 1
    assert result["maxInFlight"] == 1
    assert result["afterOldResponse"]["active"] is True
    assert "obsolete save" not in result["afterOldResponse"]["toasts"]
    patches: list[dict[str, Any]] = result["patches"]
    assert [patch["onebot.file_send_mode"] for patch in patches] == [
        "stream",
        "local",
    ]
    assert result["saved"]["onebot.file_send_mode"] == "local"
    assert result["final"]["active"] is False
    assert result["final"]["status"] == "已保存"


def test_old_auto_save_cannot_mark_debounced_edit_as_saved() -> None:
    result = run_scenario("config_autosave_typing")
    assert result["afterOldResponse"]["requestCount"] == 1
    assert result["afterOldResponse"]["active"] is True
    assert "obsolete save" not in result["afterOldResponse"]["toasts"]
    assert result["saved"]["onebot.file_send_host"] == "updated-host"
    assert result["maxInFlight"] == 1
    assert result["final"]["status"] == "已保存"


def test_saved_status_timeout_does_not_hide_new_inflight_save() -> None:
    result = run_scenario("config_autosave_saved_timer")
    assert result["whilePending"]["requestCount"] == 2
    assert result["whilePending"]["active"] is True
    assert result["whilePending"]["opacity"] == "1"
    assert result["saved"]["onebot.file_send_mode"] == "url"
    assert result["final"]["status"] == "已保存"


@pytest.mark.parametrize("outcome", ["network_error", "api_error"])
def test_latest_auto_save_failure_remains_visible_and_next_edit_can_retry(
    outcome: str,
) -> None:
    result = run_scenario(f"config_autosave_latest_{outcome}")
    assert result["afterFailure"]["requestCount"] == 2
    assert result["afterFailure"]["active"] is False
    assert "latest save failure" in result["afterFailure"]["toasts"]
    assert result["afterFailure"]["status"] == (
        "网络错误" if outcome == "network_error" else "保存失败"
    )
    assert result["saved"]["onebot.file_send_mode"] == "url"
    assert result["final"]["status"] == "已保存"
    assert result["maxInFlight"] == 1
