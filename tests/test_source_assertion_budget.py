"""源码字符串断言预算（棘轮）。

仓库里存在一类“变更检测器”测试：读取前端/资源源码文本，然后
``assert "xxx" in source``。这类断言在重构时必然变红，而真正的行为回归
却测不出来（见 ``tests/test_webui_runtime_chat_behavior.py``）。

正确的写法是行为断言：

- WebUI 脚本：用 node + ``vm`` / jsdom 执行真实 JS 再断言行为，
  参考 ``tests/test_webui_runtime_chat_behavior.py``、``tests/test_webui_config_form_frontend.py``；
- 原生 App：把断言迁到各 App 自己的 Vitest / cargo 测试里；
- Python 侧资源契约：尽量断言解析后的结构（如 JSON/TOML 字段），而不是原文子串。

历史存量一次性清不完，这里用预算棘轮收敛：**全仓源码字符串断言总数不得超过
``_BUDGET``**。新增断言会让测试失败；把断言改成行为测试后，请顺带调低预算，
让这个数字只减不增。

计数规则（刻意写得比“字面量在左、源码变量在右”宽，否则绕过方式太多）：

- 源码变量 = ``_read_source(...)`` / ``Path.read_text(...)`` 的结果（``Assign`` 与
  ``AnnAssign`` 都认），以及由它派生出来的变量（``src.split(...)[0]``、
  ``src[1:20]``、``"a" + src``、f-string …）；
- 断言 = 任何把「源码变量」与「字面量文本」放在一起比较的表达式（``in`` /
  ``==`` / ``!=`` …），以及**本身就是 ``assert`` 条件**的检索调用
  （``assert re.search(pat, src)``）；
- 字面量文本包含 ``"a" + "b"``、f-string 的静态部分、以及推导式里绑到字面量序列
  的循环变量（``any(s in src for s in ["a", "b"])``）；
- 被解析器包起来的不算：``tomllib.loads(read_text(...))["x"] == "y"`` 断言的是
  解析后的结构；``match = re.search(pat, src)`` / ``ids = set(re.findall(pat, html))``
  是提取而不是检测器。两者都是**推荐**写法，刻意不计进预算。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

_TESTS_DIR: Final[Path] = Path(__file__).resolve().parent
_SELF_NAME: Final[str] = Path(__file__).name
_SKIP_DIRS: Final[frozenset[str]] = frozenset({"__pycache__", "node_modules"})

#: 检索类函数：`re.search("x", src)` 这种「调用本身就是断言」的形态。
_SEARCH_FUNCS: Final[frozenset[str]] = frozenset(
    {"search", "match", "fullmatch", "findall", "finditer"}
)

# 当前存量 122。历史上最大的两块已经处理完：
# - tests/test_webui_runtime_chat_frontend.py（537 条）已整体迁移到 jsdom 行为测试
#   （tests/test_webui_runtime_chat_behavior.py）与解析式契约
#   （tests/test_webui_style_contracts.py / test_webui_html_preview_csp.py）；
# - 提示词文本检测（tests/test_system_prompt_constraints.py 137 条，以及
#   test_cognitive_historian.py 里的 28 条）经确认后整体删除——那类断言只是
#   "提示词里必须出现某句指导语"，改写措辞即红，并不代表能力回归。
#
# 计数规则在本轮加固过（识别 AnnAssign、派生变量、count/re.search/f-string/
# any(...) 等形态，并改成递归扫描 tests/），因此数字比旧的 72 大——旧的 72 是
# 漏数出来的，不是真的降下来了。
#
# 分布（加固后的实测值，按文件降序）：
#   40 tests/test_webui_config_form_frontend.py
#   10 tests/test_prepare_tauri_android_script.py
#   10 tests/test_webui_schedules_frontend.py
#    9 tests/test_webui_weixin_frontend.py
#    8 tests/test_naga_code_analysis_agent.py
#    7 tests/test_release_notes_script.py
#    7 tests/test_runtime_api_chat_attachments.py
#    7 tests/test_webui_logs_frontend.py
#    7 tests/test_webui_style_contracts.py
#    4 tests/test_undefined_self_code_agent.py
#    4 tests/test_webui_management_api.py
#    2 tests/test_weixin_store.py
#    1 tests/test_package_layout.py
#    1 tests/test_weixin_service.py
#
# 只允许下降：预算紧贴真实存量（零余量），新增任何一条源码字符串断言都会失败。
# 需要调高预算时请显式修改这个常量并说明原因，而不是放宽计数规则。
_BUDGET: Final[int] = 117


# --------------------------------------------------------------------------- #
# 扫描
# --------------------------------------------------------------------------- #


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _iter_test_files(base: Path = _TESTS_DIR) -> list[Path]:
    """递归收集测试文件。

    单层 ``glob("*.py")`` 会让 ``tests/子目录/*.py`` 完全不进统计，
    等于给预算开了一个后门。
    """
    return [
        path
        for path in sorted(base.rglob("*.py"))
        if path.name != _SELF_NAME and not _SKIP_DIRS.intersection(path.parts)
    ]


def _target_names(node: ast.Assign | ast.AnnAssign) -> set[str]:
    targets = list(node.targets) if isinstance(node, ast.Assign) else [node.target]
    names: set[str] = set()
    for target in targets:
        for sub in ast.walk(target):
            if isinstance(sub, ast.Name):
                names.add(sub.id)
    return names


def _is_read_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name) and func.id == "_read_source":
        return True
    return isinstance(func, ast.Attribute) and func.attr == "read_text"


def _reads_source(value: ast.expr) -> bool:
    """整个表达式是否就是「读源码」。

    只认最外层（以及链式字符串方法）：``json.loads(read_text(...))`` 得到的是
    解析后的结构，按本文件的约定那是推荐写法，不该计进预算。
    """
    node: ast.expr = value
    while True:
        if isinstance(node, ast.Await):
            node = node.value
            continue
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return _reads_source(node.left) or _reads_source(node.right)
        if isinstance(node, ast.Subscript):
            node = node.value
            continue
        if isinstance(node, ast.JoinedStr):
            return any(
                isinstance(piece, ast.FormattedValue) and _reads_source(piece.value)
                for piece in node.values
            )
        if isinstance(node, ast.Call):
            if _is_read_call(node):
                return True
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.expr):
                return _reads_source(func.value)
            return False
        return False


def _derivation_root(expr: ast.expr | None) -> str | None:
    """沿派生链向下找根变量名（``a.split(x)[0]`` → ``a``）。"""
    node = expr
    while node is not None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Subscript):
            node = node.value
            continue
        if isinstance(node, ast.Attribute):
            node = node.value
            continue
        if isinstance(node, ast.Call):
            node = node.func
            continue
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return _derivation_root(node.left) or _derivation_root(node.right)
        if isinstance(node, ast.JoinedStr):
            for piece in node.values:
                if isinstance(piece, ast.FormattedValue):
                    found = _derivation_root(piece.value)
                    if found:
                        return found
            return None
        return None
    return None


def _collect_source_vars(tree: ast.Module) -> set[str]:
    """源码变量：直接读源码的，以及由它们派生出来的（一层传递）。"""
    assignments = [
        node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    assignments.sort(key=lambda node: (node.lineno, node.col_offset))
    source_vars: set[str] = set()
    for node in assignments:
        if node.value is not None and _reads_source(node.value):
            source_vars.update(_target_names(node))
    for node in assignments:
        if node.value is None:
            continue
        root = _derivation_root(node.value)
        if root is not None and root in source_vars:
            source_vars.update(_target_names(node))
    return source_vars


def _is_literal_text(node: ast.expr) -> bool:
    """只认字面量文本（含相邻拼接与 f-string 的静态部分），不认变量名。"""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.JoinedStr):
        return any(
            isinstance(piece, ast.Constant) and isinstance(piece.value, str)
            for piece in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_literal_text(node.left) or _is_literal_text(node.right)
    return False


def _is_literal_string_sequence(node: ast.expr, literal_names: frozenset[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in literal_names
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return bool(node.elts) and all(
            _is_literal_text(element) for element in node.elts
        )
    return False


def _is_text_operand(node: ast.expr, literal_names: frozenset[str]) -> bool:
    if _is_literal_text(node):
        return True
    return isinstance(node, ast.Name) and node.id in literal_names


def _collect_literal_names(tree: ast.Module) -> set[str]:
    """绑到字面量文本的变量名（含推导式里遍历字面量序列的循环变量）。"""
    names: set[str] = set()
    for _ in range(2):
        frozen = frozenset(names)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets: list[ast.expr] = list(node.targets)
                value: ast.expr | None = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            else:
                targets, value = [], None
            if value is not None and _is_text_operand(value, frozen):
                for target in targets:
                    for sub in ast.walk(target):
                        if isinstance(sub, ast.Name):
                            names.add(sub.id)
            if isinstance(node, ast.comprehension) and _is_literal_string_sequence(
                node.iter, frozen
            ):
                for sub in ast.walk(node.target):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
    return names


def _is_source_operand(node: ast.expr, source_vars: frozenset[str]) -> bool:
    root = _derivation_root(node)
    return root is not None and root in source_vars


def _call_pool(node: ast.Call) -> list[ast.expr]:
    pool: list[ast.expr] = [*node.args]
    pool.extend(kw.value for kw in node.keywords if kw.value is not None)
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.expr):
        pool.append(func.value)
    return pool


def _is_search_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in _SEARCH_FUNCS
    return isinstance(func, ast.Attribute) and func.attr in _SEARCH_FUNCS


def _has_source_text_probe(node: ast.expr, source_vars: frozenset[str]) -> bool:
    """表达式里是否有「源码变量 + 字面量」的检索调用（``src.count("x")``）。"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and _is_literal_text_probe(sub, source_vars):
            return True
    return False


def _is_literal_text_probe(node: ast.Call, source_vars: frozenset[str]) -> bool:
    pool = _call_pool(node)
    return any(_is_source_operand(item, source_vars) for item in pool) and any(
        _is_literal_text(item) for item in pool
    )


def _probes_source_text(
    node: ast.Compare, source_vars: frozenset[str], literal_names: frozenset[str]
) -> bool:
    operands = [node.left, *node.comparators]
    has_source = any(_is_source_operand(item, source_vars) for item in operands)
    has_text = any(_is_text_operand(item, literal_names) for item in operands)
    if has_source and has_text:
        return True
    # `src.count("x") == 1` / `src.startswith("y")`：断言藏在操作数内部的调用里
    return any(_has_source_text_probe(item, source_vars) for item in operands)


def _asserted_node_ids(tree: ast.Module) -> set[int]:
    """``assert`` 条件子树里的全部节点 id。

    检索调用只有**本身就是断言条件**时才算变更检测器（裸
    ``assert re.search(pat, src)``）；被绑到变量去做解析提取的
    （``match = re.search(pat, src)`` / ``ids = set(re.findall(pat, html))``）
    属于解析式写法——那正是预算想鼓励的方向，罚它等于给出错误激励。
    """
    asserted: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            asserted.update(id(sub) for sub in ast.walk(node.test))
    return asserted


def _count_in_tree(tree: ast.Module) -> int:
    source_vars = frozenset(_collect_source_vars(tree))
    literal_names = frozenset(_collect_literal_names(tree))
    asserted = _asserted_node_ids(tree)
    counted: set[int] = set()
    total = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and _probes_source_text(
            node, source_vars, literal_names
        ):
            total += 1
            counted.update(id(sub) for sub in ast.walk(node))
    for node in ast.walk(tree):
        if id(node) in counted or id(node) not in asserted:
            continue
        if not isinstance(node, ast.Call):
            continue
        if _is_search_call(node) and _is_literal_text_probe(node, source_vars):
            total += 1
    return total


def _count_source_string_assertions(path: Path) -> int:
    return _count_in_tree(ast.parse(_read_text(path)))


def _scan() -> tuple[int, dict[str, int]]:
    per_file: dict[str, int] = {}
    for path in _iter_test_files():
        count = _count_source_string_assertions(path)
        if count:
            per_file[path.relative_to(_TESTS_DIR).as_posix()] = count
    return sum(per_file.values()), per_file


# --------------------------------------------------------------------------- #
# 计数自检：固定样本
# --------------------------------------------------------------------------- #

#: 固定样本：写死在这里的合成源码，覆盖预算最容易被绕过的一批写法。
#: 计数逻辑一旦被改坏（正则/AST 匹配失效、忘记派生变量…），这里立刻变红。
#: 期望值 6：
#:   1 `"alpha" in src`（AnnAssign 读源码）
#:   2 `src.count("beta") == 1`
#:   3 `("ga" + "gamma") in fn`（派生变量 + 常量拼接）
#:   4 `f"prefix-{MARKER}" in raw`（普通 Assign 读源码 + f-string）
#:   5 `any(part in src for part in [...])`（推导式循环变量）
#:   6 `assert re.search("zeta", src)`（检索调用**本身就是断言条件**）
#: 不计：`tomllib.loads(src)["x"] == "parsed"`（解析后的结构）、
#:       `"not-source" in unrelated`（不是源码变量）、
#:       `found = re.search("eta", src)`（提取，不是检测器——这一条同时挡住
#:       「把检索调用一律计数」的过度计数回归）。
_SELF_CHECK_SAMPLE: Final[str] = """

def _read_source(path: str) -> str:
    return open(path, encoding="utf-8").read()


def test_sample(tmp_path) -> None:
    src: str = _read_source(tmp_path / "a.js")
    raw = (tmp_path / "b.css").read_text(encoding="utf-8")
    fn = src.split("function save()", 1)[1]
    unrelated = "普通字符串"
    assert "alpha" in src
    assert src.count("beta") == 1
    assert ("ga" + "gamma") in fn
    assert f"prefix-{MARKER}" in raw
    assert any(part in src for part in ["delta", "epsilon"])
    assert re.search("zeta", src)
    found = re.search("eta", src)
    assert found
    assert tomllib.loads(src)["x"] == "parsed"
    assert "not-source" in unrelated
"""
_SELF_CHECK_EXPECTED: Final[int] = 6


def test_counter_self_check_on_fixed_sample(tmp_path: Path) -> None:
    """计数函数的自检：固定样本必须数出固定的条数。

    没有这条，计数逻辑被静默改坏（例如 AST 分支写错、只认某种写法）时，
    预算测试会「通过」，而棘轮实际上已经失效。
    """
    assert _count_in_tree(ast.parse(_SELF_CHECK_SAMPLE)) == _SELF_CHECK_EXPECTED


def test_counter_scans_subdirectories(tmp_path: Path) -> None:
    """递归扫描：``tests/子目录/*.py`` 也必须进统计（旧实现只扫一层）。"""
    nested = tmp_path / "unit" / "deep"
    nested.mkdir(parents=True)
    sample = nested / "test_nested.py"
    sample.write_text(_SELF_CHECK_SAMPLE, encoding="utf-8")

    found = _iter_test_files(tmp_path)
    assert sample in found, [path.as_posix() for path in found]
    assert _count_source_string_assertions(sample) == _SELF_CHECK_EXPECTED


# --------------------------------------------------------------------------- #
# 预算
# --------------------------------------------------------------------------- #


def test_source_string_assertions_stay_within_budget() -> None:
    total, per_file = _scan()
    top = sorted(per_file.items(), key=lambda item: -item[1])[:5]
    assert total <= _BUDGET, (
        f"源码字符串断言总数 {total} 超出预算 {_BUDGET}。\n"
        "请改为行为断言：node + vm / jsdom 执行真实 JS"
        "（参考 test_webui_runtime_chat_behavior.py）"
        "或 App 内的 Vitest / cargo 测试；解析结构化资源时断言解析结果而非原文子串。\n"
        "当前最多的文件：\n  " + "\n  ".join(f"{name}: {count}" for name, count in top)
    )


def test_budget_has_no_headroom() -> None:
    """预算必须紧贴真实存量——这正是它能发现「新增了源码字符串断言」的原因。

    预算一旦被调高到高于真实值，新增断言就能悄悄溜进去；这条把它钉死。
    确实需要放宽时，请显式修改 ``_BUDGET`` 并说明原因。
    """
    total, _ = _scan()
    assert total == _BUDGET, (
        f"实测 {total} 条，预算却是 {_BUDGET}。\n"
        f"- 存量下降：请把 _BUDGET 调低到 {total}（棘轮只允许下降）；\n"
        f"- 存量上升：说明新增了源码字符串断言，请改写成行为断言。"
    )
