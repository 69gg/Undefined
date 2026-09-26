"""源码字符串断言预算（棘轮）。

仓库里存在一类“变更检测器”测试：读取前端/资源源码文本，然后
``assert "xxx" in source``。这类断言在重构时必然变红，而真正的行为回归
却测不出来（见 ``tests/test_webui_runtime_chat_frontend.py``）。

正确的写法是行为断言：

- WebUI 脚本：用 node + ``vm`` 执行真实 JS 再断言行为，
  参考 ``tests/test_webui_config_form_frontend.py``；
- 原生 App：把断言迁到各 App 自己的 Vitest / cargo 测试里；
- Python 侧资源契约：尽量断言解析后的结构（如 JSON/TOML 字段），而不是原文子串。

历史存量一次性清不完，这里用预算棘轮收敛：**全仓源码字符串断言总数不得超过
``_BUDGET``**。新增断言会让测试失败；把断言改成行为测试后，请顺带调低预算，
让这个数字只减不增。
"""

from __future__ import annotations

import ast
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent

# 当前存量 405（其中 test_webui_runtime_chat_frontend.py 一个文件占约 142）。
# 只允许下降：新增源码字符串断言会失败。
#
# 收敛进度：WebUI 运行时聊天前端已大量迁移到 jsdom 行为测试
# （tests/test_webui_runtime_chat_behavior.py + tests/frontend/），该文件从
# 537 降到约 437；剩余大头是 test_system_prompt_constraints.py（提示词契约，
# 内容本身就是文本，适合保留）与该文件里的 CSS/模板结构性断言。
_BUDGET = 405


def _collect_source_vars(tree: ast.Module) -> set[str]:
    source_vars: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = node.value
            calls = (
                [value]
                if isinstance(value, ast.Call)
                else [c for c in ast.walk(value) if isinstance(c, ast.Call)]
            )
            for call in calls:
                func = call.func
                if (isinstance(func, ast.Name) and func.id == "_read_source") or (
                    isinstance(func, ast.Attribute) and func.attr == "read_text"
                ):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            source_vars.add(target.id)
        # 源码变量的切片/拼接结果仍视为源码变量
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Subscript):
            base = node.value.value
            while isinstance(base, ast.Subscript):
                base = base.value
            if isinstance(base, ast.Name) and base.id in source_vars:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        source_vars.add(target.id)
    return source_vars


def _count_source_string_comparisons(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    source_vars = _collect_source_vars(tree)
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Constant):
            continue
        for comparator in node.comparators:
            if isinstance(comparator, ast.Name) and comparator.id in source_vars:
                count += 1
    return count


def test_source_string_assertions_stay_within_budget() -> None:
    per_file: dict[str, int] = {}
    for path in sorted(_TESTS_DIR.glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        count = _count_source_string_comparisons(path)
        if count:
            per_file[path.relative_to(_TESTS_DIR).as_posix()] = count

    total = sum(per_file.values())
    top = sorted(per_file.items(), key=lambda kv: -kv[1])[:5]
    assert total <= _BUDGET, (
        f"源码字符串断言总数 {total} 超出预算 {_BUDGET}。\n"
        "请改为行为断言：node + vm 执行真实 JS（参考 test_webui_config_form_frontend.py）"
        "或 App 内的 Vitest / cargo 测试；解析结构化资源时断言解析结果而非原文子串。\n"
        "当前最多的文件：\n  " + "\n  ".join(f"{name}: {count}" for name, count in top)
    )
