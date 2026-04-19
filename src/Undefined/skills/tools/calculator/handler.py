"""安全的多功能数学计算器。

通过 AST 解析数学表达式，仅允许数学运算，拒绝任何危险操作。
支持：算术、幂运算、科学函数、统计函数、常量。
"""

from __future__ import annotations

import ast
import math
import operator
import statistics
from typing import Any

_UNARY_OPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_BIN_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.BitXor: operator.pow,  # ^ 也当幂运算（常见误用）
}

_COMPARE_OPS: dict[type, Any] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}

_CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "PI": math.pi,
    "e": math.e,
    "E": math.e,
    "tau": math.tau,
    "inf": math.inf,
    "nan": math.nan,
}


def _stat_fn(fn_name: str, args: list[float | int]) -> float | int:
    """统计函数分发。"""
    if len(args) < 1:
        raise ValueError(f"{fn_name} 至少需要 1 个参数")
    fn_map: dict[str, Any] = {
        "mean": statistics.mean,
        "median": statistics.median,
        "stdev": statistics.stdev,
        "variance": statistics.variance,
        "pstdev": statistics.pstdev,
        "pvariance": statistics.pvariance,
        "harmonic_mean": statistics.harmonic_mean,
    }
    fn = fn_map.get(fn_name)
    if fn is None:
        raise ValueError(f"未知统计函数: {fn_name}")
    if fn_name in ("stdev", "variance") and len(args) < 2:
        raise ValueError(f"{fn_name} 至少需要 2 个数据点")
    result: float | int = fn(args)
    return result


_MATH_FUNCS: dict[str, Any] = {
    # 基础
    "abs": abs,
    "round": round,
    "int": int,
    "float": float,
    # 幂与对数
    "sqrt": math.sqrt,
    "cbrt": lambda x: x ** (1 / 3),
    "pow": math.pow,
    "exp": math.exp,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "ln": math.log,
    # 三角
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    # 角度转换
    "degrees": math.degrees,
    "radians": math.radians,
    # 取整
    "ceil": math.ceil,
    "floor": math.floor,
    "trunc": math.trunc,
    # 组合数学
    "factorial": math.factorial,
    "comb": math.comb,
    "perm": math.perm,
    "gcd": math.gcd,
    "lcm": math.lcm,
    # 其他
    "hypot": math.hypot,
    "copysign": math.copysign,
    "fmod": math.fmod,
    "isqrt": math.isqrt,
    # 统计（占位，实际调用 _stat_fn）
    "mean": None,
    "median": None,
    "stdev": None,
    "variance": None,
    "pstdev": None,
    "pvariance": None,
    "harmonic_mean": None,
    # 最值
    "max": max,
    "min": min,
    "sum": sum,
}

_STAT_FUNCS = frozenset(
    {"mean", "median", "stdev", "variance", "pstdev", "pvariance", "harmonic_mean"}
)

_MAX_POWER = 10000
_MAX_EXPRESSION_LENGTH = 500


class _SafeEvaluator(ast.NodeVisitor):
    """安全 AST 求值器，仅允许数学运算。"""

    def visit(self, node: ast.AST) -> Any:
        return super().visit(node)

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(f"不支持的表达式语法: {type(node).__name__}")

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, (int, float, complex)):
            return node.value
        raise ValueError(f"不支持的常量类型: {type(node.value).__name__}")

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise ValueError(f"未知变量: {node.id}")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        op_fn = _UNARY_OPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"不支持的一元运算: {type(node.op).__name__}")
        return op_fn(self.visit(node.operand))

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        op_fn = _BIN_OPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"不支持的运算: {type(node.op).__name__}")
        left = self.visit(node.left)
        right = self.visit(node.right)
        if isinstance(node.op, (ast.Pow, ast.BitXor)):
            if isinstance(right, (int, float)) and abs(right) > _MAX_POWER:
                raise ValueError(f"指数过大: {right}（上限 {_MAX_POWER}）")
        return op_fn(left, right)

    def visit_Compare(self, node: ast.Compare) -> Any:
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            op_fn = _COMPARE_OPS.get(type(op))
            if op_fn is None:
                raise ValueError(f"不支持的比较: {type(op).__name__}")
            right = self.visit(comparator)
            if not op_fn(left, right):
                return False
            left = right
        return True

    def visit_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise ValueError("仅支持直接函数调用")
        fn_name = node.func.id
        if fn_name not in _MATH_FUNCS:
            raise ValueError(f"未知函数: {fn_name}")
        if node.keywords:
            raise ValueError("不支持关键字参数")

        args = [self.visit(arg) for arg in node.args]

        if fn_name in _STAT_FUNCS:
            return _stat_fn(fn_name, args)

        fn = _MATH_FUNCS[fn_name]
        return fn(*args)

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        condition = self.visit(node.test)
        return self.visit(node.body) if condition else self.visit(node.orelse)

    def visit_Tuple(self, node: ast.Tuple) -> Any:
        return tuple(self.visit(elt) for elt in node.elts)

    def visit_List(self, node: ast.List) -> Any:
        return [self.visit(elt) for elt in node.elts]


def safe_eval(expression: str) -> str:
    """安全计算数学表达式，返回字符串结果。"""
    expr = expression.strip()
    if not expr:
        raise ValueError("表达式为空")
    if len(expr) > _MAX_EXPRESSION_LENGTH:
        raise ValueError(
            f"表达式过长（{len(expr)} 字符，上限 {_MAX_EXPRESSION_LENGTH}）"
        )

    tree = ast.parse(expr, mode="eval")
    result = _SafeEvaluator().visit(tree)

    if isinstance(result, float):
        if result == int(result) and not (math.isinf(result) or math.isnan(result)):
            return str(int(result))
        return f"{result:.10g}"
    if isinstance(result, complex):
        return str(result)
    if isinstance(result, bool):
        return str(result)
    return str(result)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """计算数学表达式。"""
    expression = str(args.get("expression", "")).strip()
    if not expression:
        return "请提供数学表达式"

    try:
        result = safe_eval(expression)
        return f"{expression} = {result}"
    except ZeroDivisionError:
        return f"计算错误：除以零 ({expression})"
    except OverflowError:
        return f"计算错误：结果溢出 ({expression})"
    except (ValueError, TypeError) as exc:
        return f"计算错误：{exc}"
    except SyntaxError:
        return f"表达式语法错误：{expression}"
