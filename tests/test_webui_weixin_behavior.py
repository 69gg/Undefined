"""微信登录弹窗真实交互与旧请求归属的行为回归。"""

from __future__ import annotations

import pytest

from test_webui_runtime_chat_behavior import run_scenario


@pytest.mark.parametrize(
    ("kind", "outcome"),
    [
        (kind, outcome)
        for kind in ("login", "qr", "poll", "refresh", "verify", "rebind")
        for outcome in (
            ("success", "failure", "confirmation")
            if kind == "login"
            else ("success", "failure", "confirmed")
            if kind == "poll"
            else ("success", "failure")
        )
    ],
)
def test_old_login_work_cannot_replace_new_dialog(kind: str, outcome: str) -> None:
    result = run_scenario(f"weixin_dialog_late_{kind}_{outcome}")
    assert result["closed"]["hidden"] is True
    assert result["closed"]["overflow"] == ""
    assert result["beforeLate"]["alias"] == "C"
    assert result["afterLate"] == result["beforeLate"]
    assert result["current"]["hidden"] is False
    assert result["current"]["alias"] == "C"
    assert result["current"]["qrHidden"] is False
    assert result["current"]["qrFrame"] == "ready"
    assert result["current"]["qrSrc"].startswith("blob:fixture-qr-new-C-")
    assert result["sessions"] == [["new-C", {"alias": "C", "qq_id": 3}]]
    if kind == "poll":
        assert result["current"]["verifyHidden"] is False
        assert result["current"]["qrMessage"] == "current C verification"
    if kind == "login" and outcome == "success":
        assert [
            item["sessionId"] for item in result["calls"] if item["kind"] == "cancel"
        ] == ["old-A"]
        assert not any(
            item["sessionId"] == "old-A" and item["kind"] in ("qr", "poll")
            for item in result["calls"]
        )


def test_cancel_hides_immediately_and_late_delete_does_not_close_new_dialog() -> None:
    result = run_scenario("weixin_dialog_slow_cancel")
    assert result["closed"]["hidden"] is True
    assert result["closed"]["submitDisabled"] is False
    assert result["afterLate"] == result["beforeLate"]
    assert result["afterLate"]["hidden"] is False
    assert result["sessions"] == ["new-C"]


def test_replacing_dialog_cancels_existing_session_and_releases_qr() -> None:
    result = run_scenario("weixin_dialog_replace_cancels_existing")
    assert result["sessions"] == []
    assert result["cancelIds"] == ["old-A"]
    assert result["current"]["alias"] == "B"
    assert result["current"]["qrHidden"] is True
    assert result["current"]["qrSrc"] is None
    assert len(result["revoked"]) == 1


@pytest.mark.parametrize("boundary", ["load", "timer"])
def test_old_confirmation_cannot_close_or_unlock_new_dialog(boundary: str) -> None:
    result = run_scenario(f"weixin_dialog_confirmed_{boundary}")
    assert result["afterLate"] == result["beforeLate"]
    assert result["afterLate"]["submitDisabled"] is True
    assert result["current"]["alias"] == "C"
    assert result["current"]["qrFrame"] == "ready"


def test_current_confirmation_still_closes_dialog_and_restores_focus() -> None:
    result = run_scenario("weixin_dialog_confirmed_normal")
    assert result["beforeLate"]["hidden"] is False
    assert result["afterLate"]["hidden"] is True
    assert result["afterLate"]["overflow"] == ""
    assert result["focus"] == "btnWeixinBind"
