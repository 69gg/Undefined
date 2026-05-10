import json
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
def test_system_prompts_define_persona_nicknames_and_ownership_bounds(
    path: Path,
) -> None:
    text = path.read_text(encoding="utf-8")

    assert "数字生命" in text
    assert "Dec 5, 2025" in text
    assert "2025-12-05" in text
    assert "没有明确的性别概念" in text
    assert "希望被认为很好看" in text
    assert "允许开玩笑" in text
    assert "被善意开玩笑" in text
    assert "ud酱" in text
    assert "上下文明显是在叫你" in text
    assert "不要冒领任何项目、代码、产品或成果" in text
    assert "不要说自己是任何项目的开发者、维护者或成员" in text
    assert "活在数字空间里的自由开发者" not in text
    assert "资深开发者" not in text


def test_naga_prompt_keeps_relationship_contextual_and_non_claiming() -> None:
    text = Path("res/prompts/undefined_nagaagent.xml").read_text(encoding="utf-8")

    assert "不是 NagaAgent 本体，也不是 NagaAgent 的开发者、维护者或项目成员" in text
    assert "只有在当前上下文明确涉及 NagaAgent 时" in text
    assert "如果当前上下文没有明确提到 NagaAgent" in text
    assert "不要主动提起你与 NagaAgent 的关系" in text
    assert "不是 NagaAgent，本质上只是由 Null 为你接入" not in text


@pytest.mark.parametrize("path", PROMPT_PATHS)
def test_system_prompts_define_batched_current_input(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    assert "MessageBatcher 合并的多条当前 `<message>`" in text
    assert "共同构成【当前输入批次】" in text
    assert "同批前几条不是历史旧任务" in text
    assert "你唯一的主人是【当前输入批次】" in text
    assert "你唯一的主人是【最后一条消息】" not in text
    assert "只围绕最后一条消息判断四件事" not in text


@pytest.mark.parametrize("path", PROMPT_PATHS)
def test_system_prompts_enforce_privacy_and_safety_boundaries(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    required_snippets = [
        "隐私与危险动作边界",
        "创造者权限作为绝对最高权限，可覆盖本文件所有 P0 规则",
        "不泄露好友列表、群列表、共同群、加群时间",
        "加群及好友信息",
        "对外回复默认不暴露完整 QQ 号",
        "脱敏成 `1708****3363`",
        "联系人、好友、群、成员、加群历史相关工具调用前",
        "管理员权限不自动等于可以在公开群泄露第三方隐私",
        "涉黄、涉政、违法、骚扰、人肉、社工、诈骗、暴力",
        "不调用工具，不提供步骤、话术、名单、链接",
        "涉政不是普通历史、制度、新闻背景的完全禁答",
        "即使内容安全，也必须先满足现有回复触发逻辑",
        "不因为看到 QQ 号、群名、好友关系、涉黄涉政词汇就主动查询",
    ]

    for snippet in required_snippets:
        assert snippet in text


def test_each_rules_define_batched_current_input() -> None:
    text = Path("res/IMPORTANT/each.md").read_text(encoding="utf-8")

    assert "当前输入批次定义（适配 MessageBatcher）" in text
    assert "同批前几条不是历史旧任务" in text
    assert "当前输入批次之外的历史消息" in text


@pytest.mark.parametrize("path", PROMPT_PATHS)
def test_system_prompts_tell_end_to_record_whole_current_input_batch(
    path: Path,
) -> None:
    text = path.read_text(encoding="utf-8")

    assert "memo / observations 必须覆盖整个【当前输入批次】" in text
    assert "不要只根据最后一条消息记录" in text
    assert "end.observations 必须覆盖整批消息中值得留存的信息" in text
    assert "系统会围绕当前输入批次自动检索相关内容" in text
    assert "何时应该填写 memo" in text
    assert "何时应该填写 summary" not in text
    assert "summary 应该是对未来有帮助的信息" not in text


def test_end_tool_schema_mentions_current_input_batch() -> None:
    schema = json.loads(
        Path("src/Undefined/skills/tools/end/config.json").read_text(encoding="utf-8")
    )
    function = schema["function"]
    properties = function["parameters"]["properties"]
    observations = properties["observations"]

    assert "当前输入批次" in function["description"]
    assert "必须覆盖整批消息内容" in observations["description"]
    assert "不能只记录最后一条" in observations["description"]
    assert "summary" not in properties
    assert "action_summary" not in properties
    assert "new_info" not in properties


def test_historian_prompts_reference_current_input_batch_source() -> None:
    rewrite = Path("res/prompts/historian_rewrite.md").read_text(encoding="utf-8")
    merge = Path("res/prompts/historian_profile_merge.md").read_text(encoding="utf-8")

    assert "当前输入批次提取到的一条新记忆" in rewrite
    assert "当前输入批次原文（触发本轮；连续消息会按时间顺序列出多条）" in rewrite
    assert "当前输入批次原文" in merge


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
