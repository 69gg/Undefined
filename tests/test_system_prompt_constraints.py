from pathlib import Path

import pytest


PROMPT_PATHS = [
    Path("res/prompts/undefined.xml"),
    Path("res/prompts/undefined_nagaagent.xml"),
]


@pytest.mark.parametrize("path", PROMPT_PATHS)
def test_system_prompts_include_info_gate_and_style_constraints(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    required_snippets = [
        "启动前信息充足度闸门",
        "信息不足时的唯一允许动作",
        "信息闸门与防幽灵任务的适配",
        "禁止因为历史里存在更完整的旧任务，就借它补齐参数后直接启动",
        "客服尾巴也算客服腔",
        "<name>结尾收住</name>",
        '<case id="info_gap_requires_clarification"',
        '<case id="latest_message_cannot_revive_old_task"',
    ]

    for snippet in required_snippets:
        assert snippet in text


def test_naga_prompt_requires_scope_before_naga_analysis() -> None:
    text = Path("res/prompts/undefined_nagaagent.xml").read_text(encoding="utf-8")

    assert "直接把宽泛问题丢给 naga_code_analysis_agent" in text
    assert (
        "先追问具体模块 / 报错 / 现象；只有范围收窄后再调用 naga_code_analysis_agent"
        in text
    )
