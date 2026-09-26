"""WebUI 样式契约的解析式断言辅助。

原先这类测试把 CSS 当纯文本、用 `assert "min-width: 0;" in css` 判断属性是否存在——
改个格式就红，而真正的样式回归（某条规则被删、值被换）未必测得到。

这里提供一个**最小 CSS 解析器**：按选择器取出声明块，再断言解析得到的
``属性 -> 值`` 映射。仍然不理解层叠与优先级（那是浏览器的事），但足以表达
「这条规则里必须有这个属性且值正确」。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

CSS_DIR: Final[Path] = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "Undefined"
    / "webui"
    / "static"
    / "css"
)

#: 单条声明：``属性: 值``（值里可能含逗号、括号、变量）。
_DECLARATION = re.compile(r"([a-zA-Z-]+)\s*:\s*([^;{}]+)")

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


class Stylesheet:
    """一份解析后的样式表：选择器 -> 声明序列（按出现顺序）。"""

    def __init__(self, rules: list[tuple[str, dict[str, str]]]) -> None:
        self._rules = rules

    @classmethod
    def load(cls, name: str) -> "Stylesheet":
        path = CSS_DIR / name
        text = _COMMENT.sub("", path.read_text(encoding="utf-8"))
        rules: list[tuple[str, dict[str, str]]] = []
        # 只处理顶层块；@media 等嵌套块会被拆成其中的规则（选择器原样保留）
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
            selector = " ".join(match.group(1).split())
            if not selector or selector.startswith("@"):
                continue
            declarations: dict[str, str] = {}
            for name_part, value_part in _DECLARATION.findall(match.group(2)):
                declarations[name_part.lower()] = " ".join(value_part.split())
            rules.append((selector, declarations))
        return cls(rules)

    def selectors(self) -> list[str]:
        return [selector for selector, _ in self._rules]

    def declarations(self, selector: str) -> dict[str, str]:
        """取某选择器的声明；同一选择器出现多次时**合并**（后者覆盖前者）。

        样式中同一选择器可能分散在多处（例如基础规则 + 响应式覆盖），合并后
        更贴近「这些属性最终是否被声明过」。
        """
        merged: dict[str, str] = {}
        found = False
        for rule_selector, declarations in self._rules:
            if rule_selector != selector:
                continue
            found = True
            merged.update(declarations)
        assert found, (
            f"样式中找不到选择器 {selector!r}；现有选择器示例：{self.selectors()[:8]}"
        )
        return merged

    def selectors_containing(self, fragment: str) -> list[str]:
        return [selector for selector in self.selectors() if fragment in selector]

    def declarations_matching(self, fragment: str) -> list[dict[str, str]]:
        """取所有选择器含该片段的规则的声明。"""
        return [
            declarations
            for selector, declarations in self._rules
            if fragment in selector
        ]
