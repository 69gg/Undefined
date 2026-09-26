"""提示词的结构与体量契约（**不匹配措辞**）。

背景：原先的 ``tests/test_system_prompt_constraints.py`` 逐句断言「提示词里必须
出现某句指导语」，改写措辞即红、但并不代表能力回归，已在确认后整体删除。删除
同时也失去了一层保护——v3.15 那版改动曾把提示词从 1958 行压到 1920 行、静默丢掉
34 行指导语，而没有任何测试发现。

本文件用**不依赖措辞**的维度补回这层保护：

- **结构**：顶层小节的名字与顺序（改动必须显式确认，不能静默增删）
- **体量**：行数棘轮，只允许增长或小幅波动，防止静默缩水
- **一致性**：两个提示词变体的结构必须同步演进
- **格式契约**：Markdown 提示词里的模板占位符（``{now_local}`` 等）是功能性
  契约，改动会影响渲染
- **渲染槽位**：``<!-- undefined:prompt-file-include:... -->`` 是渲染器依赖的
  锚点，删掉之后该插槽静默失效
- **负向协议**：真实提示词里不得出现文本形式的工具调用协议痕迹

刻意**不**断言：任何一句指导语的具体文字、小节内部的段落结构、标签是否良构
（已知提示词存在历史遗留的标签不匹配，见 ``KNOWN_TAG_MISMATCHES``）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from Undefined.config.models import PROMPT_FILE_INCLUDE_SLOTS

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
PROMPTS: Final[Path] = REPO_ROOT / "res" / "prompts"
IMPORTANT: Final[Path] = REPO_ROOT / "res" / "IMPORTANT"

BASE_PROMPT: Final[Path] = PROMPTS / "undefined.xml"
NAGA_PROMPT: Final[Path] = PROMPTS / "undefined_nagaagent.xml"
HISTORIAN_MERGE: Final[Path] = PROMPTS / "historian_profile_merge.md"
HISTORIAN_REWRITE: Final[Path] = PROMPTS / "historian_rewrite.md"
EACH_RULES: Final[Path] = IMPORTANT / "each.md"

#: 顶层小节的名字与顺序。增删或重排都必须同步改这里——这正是契约的意义：
#: 让结构变化成为一次**显式决定**，而不是悄悄发生。
EXPECTED_SECTIONS: Final[tuple[str, ...]] = (
    "absolute_priority",
    "core_rules",
    "important_rules",
    "optimization_rules",
    "scenario_examples",
    "decision_regression_suite",
    "priority_conflict_resolution",
    "summary",
)

#: 行数下限（棘轮）：低于此值说明有内容被静默删掉，需要显式下调并说明原因。
#: 取值低于当前实测行数约 10%，允许正常润色带来的小幅收缩。
MIN_LINES: Final[dict[str, int]] = {
    "prompts/undefined.xml": 1345,
    "prompts/undefined_nagaagent.xml": 1410,
    "prompts/historian_profile_merge.md": 162,
    "prompts/historian_rewrite.md": 45,
    "IMPORTANT/each.md": 70,
}

#: 两个变体的体量差异上限：NagaAgent 变体只是在基础版上增补，不应大幅偏离。
MAX_VARIANT_RATIO: Final[float] = 1.25

#: 已知的标签不匹配处（历史遗留，两个文件一致）。这里**如实登记**而不是断言它
#: 良构：一旦数量变化，说明有人动过结构，应显式确认是新缺陷还是修好了。
KNOWN_TAG_MISMATCHES: Final[int] = 10

#: 顶层小节的开标签：必须排除闭标签（`</name>` 也形如 `  <...`，早期实现因此
#: 把闭标签一并当成开标签，导致配对检查恒真——变异测试才暴露出来）。
_TOP_SECTION = re.compile(r"^  <(?!/)([a-zA-Z_][\w.-]*)(?:\s|>)", re.MULTILINE)
_TAG = re.compile(r"</?([a-zA-Z_][\w.-]*)(?:\s[^>]*)?/?>")

#: 文件插槽标记，与 ``ai/prompts/file_includes.py`` 的行内锚点正则同构
#: （这里不锚行首，便于统计出现次数）。
_SLOT_MARKER = re.compile(
    r"<!--\s*undefined:prompt-file-include:(?P<slot>[a-z0-9_-]+)\s*-->"
)

#: 文本工具回退协议的痕迹。系统提示词里一旦出现这些串，模型会照着抄成「文本形式
#: 的工具调用」，而真实工具调用走的是 function calling 通道——这是功能性契约，
#: 与措辞无关。原本由已删除的 test_system_prompt_constraints.py 守着。
FORBIDDEN_TOOL_PROTOCOL_MARKERS: Final[tuple[str, ...]] = (
    '{"tool"',
    "<tool name=",
    "<tool_execution>",
    "<function_calls>",
    "<invoke name=",
    "<function=",
    "<parameter=",
    " params=",
    " parameters=",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def top_sections(path: Path) -> list[str]:
    """取出按缩进识别的顶层小节（只认开标签，不依赖 XML 良构）。"""
    return [m.group(1) for m in _TOP_SECTION.finditer(_text(path))]


def standalone_section_closers(path: Path) -> list[str]:
    """取出「独立成行、缩进为 2 空格」的闭标签——即顶层小节的收尾。

    用于配对检查：只改开标签名（漏改闭标签）时，``top_sections`` 因为闭标签不再
    被当成开标签而看不出问题，这类结构性疏忽必须另行抓出。
    """
    closers: list[str] = []
    for line in _text(path).splitlines():
        match = re.fullmatch(r"  </([a-zA-Z_][\w.-]*)>", line)
        if match:
            closers.append(match.group(1))
    return closers


def count_tag_mismatches(path: Path) -> int:
    """统计闭合标签与栈顶不匹配的次数。

    提示词存在历史遗留的不匹配，因此这里只做**计数登记**，不做良构断言。
    """
    stack: list[str] = []
    mismatches = 0
    for line in _text(path).splitlines():
        for match in _TAG.finditer(line):
            raw, tag = match.group(0), match.group(1)
            if raw.startswith("</"):
                if stack and stack[-1] == tag:
                    stack.pop()
                else:
                    mismatches += 1
            elif not raw.endswith("/>"):
                stack.append(tag)
    return mismatches


# --------------------------------------------------------------------------- #
# 结构
# --------------------------------------------------------------------------- #


def test_prompt_sections_match_contract() -> None:
    """顶层小节的名字与顺序必须与契约一致。

    这是取代逐句断言的**结构层**保护：删掉一整节（例如信息闸门）会立刻失败，
    但改写节内措辞不会。
    """
    for name, path in (
        ("undefined.xml", BASE_PROMPT),
        ("undefined_nagaagent.xml", NAGA_PROMPT),
    ):
        sections = top_sections(path)
        assert tuple(sections) == EXPECTED_SECTIONS, (
            f"{name} 的顶层小节与契约不一致：{sections}\n"
            f"若是有意调整，请同步更新 EXPECTED_SECTIONS"
        )


def test_prompt_variants_share_the_same_structure() -> None:
    """两个变体必须同步演进：结构不一致说明其中一个漏了更新。"""
    assert top_sections(BASE_PROMPT) == top_sections(NAGA_PROMPT)


def test_every_section_has_a_matching_closing_tag() -> None:
    """每个顶层小节的开/闭标签必须同名。

    只改开标签名而漏改闭标签是一类静默的结构破坏：``top_sections`` 认不出问题
    （闭标签不再是"开标签"），必须靠配对检查兜住。
    """
    for name, path in (
        ("undefined.xml", BASE_PROMPT),
        ("undefined_nagaagent.xml", NAGA_PROMPT),
    ):
        openers = top_sections(path)
        closers = standalone_section_closers(path)
        assert len(openers) == len(closers), (
            f"{name} 顶层开标签 {len(openers)} 个、闭标签 {len(closers)} 个，数量不符"
        )
        # 按**位置**配对，而不是比较集合：只改开标签名时两者数量不变，
        # 集合比较抓不到这类改名遗漏。
        mismatched = [
            (index + 1, opener, closer)
            for index, (opener, closer) in enumerate(zip(openers, closers))
            if opener != closer
        ]
        assert mismatched == [], (
            f"{name} 第 i 个小节的开/闭标签不同名（序号, 开, 闭）：{mismatched}"
        )


def test_prompt_has_no_duplicate_sections() -> None:
    """小节不得重复定义（复制粘贴事故会把同一节写两遍）。"""
    sections = top_sections(BASE_PROMPT)
    duplicates = sorted({name for name in sections if sections.count(name) > 1})
    assert not duplicates, f"重复的顶层小节：{duplicates}"


# --------------------------------------------------------------------------- #
# 体量（防静默缩水）
# --------------------------------------------------------------------------- #


def test_prompt_files_do_not_shrink_below_floor() -> None:
    """行数下限棘轮：静默删掉整段指导语必须失败。

    v3.15 曾把 ``undefined.xml`` 从 1958 行压到 1920 行并丢掉 34 行内容，
    当时没有任何测试发现。这条用来兜住同类事故——它不关心写了什么，只关心
    「有没有被大量删掉」。
    """
    for key, floor in MIN_LINES.items():
        path = REPO_ROOT / "res" / key
        assert path.is_file(), f"提示词文件不存在：{path}"
        lines = len(_text(path).splitlines())
        assert lines >= floor, (
            f"{key} 只剩 {lines} 行，低于下限 {floor}；若非有意精简，说明内容被静默删除"
        )


def test_prompt_variants_stay_close_in_size() -> None:
    """NagaAgent 变体只是增补，体量不应与基础版大幅偏离。"""
    base = len(_text(BASE_PROMPT).splitlines())
    naga = len(_text(NAGA_PROMPT).splitlines())
    ratio = max(base, naga) / max(1, min(base, naga))
    assert ratio <= MAX_VARIANT_RATIO, (
        f"两个变体体量差异过大：base={base} naga={naga}（比值 {ratio:.2f}）"
    )


def test_prompts_are_not_empty_or_truncated() -> None:
    """每个提示词都必须有实质内容（防止被清空或截断成一个根标签）。"""
    for path in (
        BASE_PROMPT,
        NAGA_PROMPT,
        HISTORIAN_MERGE,
        HISTORIAN_REWRITE,
        EACH_RULES,
    ):
        text = _text(path)
        assert text.strip(), f"{path.name} 为空"
        assert len(text.splitlines()) > 20, f"{path.name} 内容过短，疑似被截断"


# --------------------------------------------------------------------------- #
# 格式契约（功能性，不是措辞）
# --------------------------------------------------------------------------- #


def _placeholders(path: Path) -> set[str]:
    return set(re.findall(r"\{([a-z_][a-z0-9_]*)\}", _text(path)))


def test_historian_profile_merge_keeps_template_placeholders() -> None:
    """这组占位符是渲染契约：渲染器会替换它们，删掉会导致提示词里出现裸花括号。"""
    required = {"now_local", "now_utc", "profile_updated_at"}
    missing = sorted(required - _placeholders(HISTORIAN_MERGE))
    assert not missing, f"historian_profile_merge.md 缺少模板占位符：{missing}"


def test_known_tag_mismatch_count_is_registered() -> None:
    """登记提示词里已知的标签不匹配数量。

    不断言良构（现状并非良构，且两个文件一致，属于历史遗留），但数量一旦变化就
    必须显式确认：是新引入了缺陷，还是把旧的修好了。修好后请把
    ``KNOWN_TAG_MISMATCHES`` 归零。
    """
    for name, path in (
        ("undefined.xml", BASE_PROMPT),
        ("undefined_nagaagent.xml", NAGA_PROMPT),
    ):
        actual = count_tag_mismatches(path)
        assert actual == KNOWN_TAG_MISMATCHES, (
            f"{name} 的标签不匹配数为 {actual}，与登记的 {KNOWN_TAG_MISMATCHES} 不符；"
            "请确认是修好了（归零登记）还是新引入了缺陷"
        )


# --------------------------------------------------------------------------- #
# 渲染槽位（功能性，不是措辞）
# --------------------------------------------------------------------------- #


def _slot_markers(text: str) -> list[str]:
    return [match.group("slot") for match in _SLOT_MARKER.finditer(text)]


def test_real_prompts_keep_every_file_include_slot_exactly_once() -> None:
    """真实提示词里每个文件插槽必须恰好出现一次。

    ``ai/prompts/file_includes.py`` 靠这些 HTML 注释锚点把外部文件插进主提示词；
    ``tests/test_prompt_file_includes.py`` 全用合成字符串，所以把真实提示词里的
    槽位删掉（或写重）没有任何用例会红——插槽会静默失效。

    槽位清单取自 ``config.models.PROMPT_FILE_INCLUDE_SLOTS``（唯一事实来源），
    出现未知槽位（例如手滑写成 ``p4``）同样会失败。
    """
    for name, path in (
        ("undefined.xml", BASE_PROMPT),
        ("undefined_nagaagent.xml", NAGA_PROMPT),
    ):
        slots = _slot_markers(_text(path))
        assert sorted(slots) == sorted(PROMPT_FILE_INCLUDE_SLOTS), (
            f"{name} 的文件插槽与契约不符：实际 {sorted(slots)}，"
            f"契约 {sorted(PROMPT_FILE_INCLUDE_SLOTS)}（缺失或重复都会在这里暴露）"
        )


# --------------------------------------------------------------------------- #
# 负向协议契约（功能性，不是措辞）
# --------------------------------------------------------------------------- #


def test_system_prompts_have_no_text_tool_protocol_traces() -> None:
    """真实系统提示词里不得出现文本形式的工具调用协议痕迹。

    模型会在提示词里「找格式」：一旦看到 ``{"tool"`` / ``<tool name=`` /
    ``<function_calls>`` 这类串，就会把它们当成输出格式照抄，绕过真实的
    function calling 通道。这是功能性契约，与措辞无关——原本由已删除的
    ``test_system_prompt_constraints.py`` 覆盖。

    覆盖范围是**参与真实拼装**的全部文本：两个主提示词变体与
    ``res/IMPORTANT/each.md``（后者同样会被拼进系统提示词，当前是干净的）。
    """
    prompt_files = sorted(PROMPTS.glob("*.xml")) + sorted(IMPORTANT.glob("*.md"))
    assert prompt_files, f"没有找到系统提示词：{PROMPTS} / {IMPORTANT}"
    for path in prompt_files:
        text = _text(path)
        hits = [marker for marker in FORBIDDEN_TOOL_PROTOCOL_MARKERS if marker in text]
        assert not hits, (
            f"{path.name} 里出现了文本工具协议的痕迹 {hits}；"
            "模型会照抄成文本形式的工具调用，请改用真实通道的描述方式"
        )
