"""工作流编辑器通过真实按钮与异步回包交错保存的行为回归。"""

from __future__ import annotations

import pytest

from test_webui_runtime_chat_behavior import run_scenario


@pytest.mark.parametrize("target", ["edited", "typing", "refresh"])
def test_save_preserves_later_edit_and_saves_it_on_next_click(target: str) -> None:
    result = run_scenario(f"workflow_editor_save_{target}")
    assert result["firstSave"] == {"method": "PATCH", "name": "first-edit"}
    assert result["afterResponse"]["input"] == "later-edit"
    assert result["afterResponse"]["page"] == "editor"
    assert result["afterResponse"]["status"] == "草稿"
    if target != "typing":
        assert result["afterResponse"]["graphName"] == "later-edit"
        assert result["afterResponse"]["dirty"] is True
    assert result["secondSave"] == {
        "url": "/api/runtime/automations/A",
        "method": "PATCH",
        "name": "later-edit",
    }
    assert result["final"]["dirty"] is False
    assert result["final"]["page"] == "list"


@pytest.mark.parametrize("target", ["switch", "same", "switch_failure", "same_failure"])
def test_old_save_cannot_replace_reopened_editor(target: str) -> None:
    result = run_scenario(f"workflow_editor_save_{target}")
    assert result["afterResponse"] == result["beforeResponse"]
    assert result["afterResponse"]["input"] == (
        "B-original" if target.startswith("switch") else "A-original"
    )
    assert result["afterResponse"]["page"] == "editor"


def test_new_task_keeps_later_draft_and_uses_assigned_id_for_next_save() -> None:
    result = run_scenario("workflow_editor_save_new")
    assert result["firstSave"] == {"method": "POST", "name": "first-edit"}
    assert result["afterResponse"]["input"] == "later-edit"
    assert result["afterResponse"]["graphName"] == "later-edit"
    assert result["afterResponse"]["dirty"] is True
    assert result["afterResponse"]["status"] == "草稿"
    assert result["afterResponse"]["id"] == "created"
    assert result["afterResponse"]["idDisabled"] is True
    assert result["secondSave"] == {
        "url": "/api/runtime/automations/created",
        "method": "PATCH",
        "name": "later-edit",
    }
    assert result["final"]["dirty"] is False


def test_unchanged_save_updates_baseline_and_returns_to_list() -> None:
    result = run_scenario("workflow_editor_save_normal")
    assert result["afterResponse"]["input"] == "first-edit"
    assert result["afterResponse"]["graphName"] == "first-edit"
    assert result["afterResponse"]["dirty"] is False
    assert result["afterResponse"]["page"] == "list"
    assert result["afterResponse"]["status"] == "自动化已保存"


@pytest.mark.parametrize("target", ["switch", "edit"])
@pytest.mark.parametrize("outcome", ["response", "failure"])
def test_late_validation_cannot_replace_current_editor_issues(
    target: str, outcome: str
) -> None:
    result = run_scenario(f"workflow_editor_validation_{target}_{outcome}")
    assert (
        result["afterResponse"]["issueBadge"] == result["beforeResponse"]["issueBadge"]
    )
    assert result["afterResponse"]["input"] == (
        "B-current-edit" if target == "switch" else "current-edit"
    )
