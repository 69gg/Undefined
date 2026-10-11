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


@pytest.mark.parametrize("operation", ["restore", "sync", "reload", "restore_sync"])
def test_config_replacement_discards_old_snapshots_and_waits_for_inflight_save(
    operation: str,
) -> None:
    result = run_scenario(f"config_replacement_{operation}")
    assert result["beforeResponse"] == {
        "patchCount": 1,
        "mutationCount": 0,
        "formInert": True,
    }
    assert result["patchCount"] == 1
    assert (
        result["serverMode"]
        == result["formMode"]
        == ("local" if operation.startswith("restore") else "stream")
    )
    assert result["formInert"] is False
    assert "obsolete save warning" not in result["toasts"]
    if operation == "restore_sync":
        assert result["calls"].index("/api/config/history/restore") < result[
            "calls"
        ].index("/api/config/sync-template?write=false")


@pytest.mark.parametrize("outcome", ["http", "api", "network"])
def test_failed_config_restore_preserves_form_and_allows_retry(outcome: str) -> None:
    result = run_scenario(f"config_replacement_restore_failure_{outcome}")
    failure = result["afterFailure"]
    assert failure["formMode"] == "url"
    assert failure["formHost"] == "obsolete-host"
    assert failure["formInert"] is False
    assert failure["panelVisible"] is True
    assert failure["summaryCount"] == 1
    assert "isolated restore failure" in failure["toasts"]
    assert "已恢复配置" not in failure["toasts"]
    assert result["serverMode"] == result["formMode"] == "local"
    assert result["formInert"] is False
    assert result["patchCount"] == 1
    assert result["calls"].count("/api/config/history/restore") == 2
    assert "已恢复配置" in result["toasts"]
