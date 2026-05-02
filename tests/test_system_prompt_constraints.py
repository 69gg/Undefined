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


@pytest.mark.parametrize("path", PROMPT_PATHS)
def test_system_prompts_keep_proactive_participation_narrow_and_meme_post_reply(
    path: Path,
) -> None:
    text = path.read_text(encoding="utf-8")

    assert (
        "群里在讨论你擅长或感兴趣的技术或项目话题（代码、AI、开发工具、项目进展、技术 bug 等）"
        in text
    )
    assert "表情包相关规则只决定“怎么回复”，不单独构成“该不该回复”的参与许可" in text
    assert "只有当本轮回复目标明确是“纯表情包/纯反应图”" in text
    assert "不要为了“增强语气”在首轮抢先调用 `memes.search_memes`" in text
    assert "第一轮必须优先把必要文字回复做好并调用 `send_message`" in text
    assert "如果本轮既需要文字发言又想配表情包" in text
    assert "先调用 `send_message` 发出必要文字" in text
    assert "表情包检索可能拖慢首条回复体验" in text
    assert "再把表情包检索和发送放到后续轮次" in text
    assert "群里有多人在公开讨论你擅长或感兴趣的话题" not in text
    assert "有人说了明显有趣/好笑的话，你有自然的回应冲动" not in text
