"""calculator 工具单元测试。"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from Undefined.skills.tools.calculator.handler import safe_eval

TOOL_DIR = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "Undefined"
    / "skills"
    / "tools"
    / "calculator"
)


# ---------------------------------------------------------------------------
# 配置文件检查
# ---------------------------------------------------------------------------


class TestConfig:
    def test_config_json(self) -> None:
        cfg: dict[str, Any] = json.loads(
            (TOOL_DIR / "config.json").read_text(encoding="utf-8")
        )
        assert cfg["function"]["name"] == "calculator"
        assert "expression" in cfg["function"]["parameters"]["properties"]

    def test_callable_json(self) -> None:
        cfg: dict[str, Any] = json.loads(
            (TOOL_DIR / "callable.json").read_text(encoding="utf-8")
        )
        assert cfg["enabled"] is True
        assert "*" in cfg["allowed_callers"]


# ---------------------------------------------------------------------------
# safe_eval 单元测试
# ---------------------------------------------------------------------------


class TestArithmetic:
    def test_addition(self) -> None:
        assert safe_eval("2+3") == "5"

    def test_subtraction(self) -> None:
        assert safe_eval("10-3") == "7"

    def test_multiplication(self) -> None:
        assert safe_eval("4*5") == "20"

    def test_division(self) -> None:
        assert safe_eval("10/3") == "3.333333333"

    def test_floor_division(self) -> None:
        assert safe_eval("10//3") == "3"

    def test_modulo(self) -> None:
        assert safe_eval("10%3") == "1"

    def test_power(self) -> None:
        assert safe_eval("2**10") == "1024"

    def test_caret_as_power(self) -> None:
        assert safe_eval("2^10") == "1024"

    def test_negative_number(self) -> None:
        assert safe_eval("-5+3") == "-2"

    def test_complex_expression(self) -> None:
        assert safe_eval("(2+3)*4-1") == "19"

    def test_floating_point(self) -> None:
        assert safe_eval("0.1+0.2") == "0.3"


class TestConstants:
    def test_pi(self) -> None:
        result = float(safe_eval("pi"))
        assert abs(result - math.pi) < 1e-8

    def test_e(self) -> None:
        result = float(safe_eval("e"))
        assert abs(result - math.e) < 1e-8

    def test_tau(self) -> None:
        result = float(safe_eval("tau"))
        assert abs(result - math.tau) < 1e-8


class TestScientificFunctions:
    def test_sqrt(self) -> None:
        assert safe_eval("sqrt(144)") == "12"

    def test_sin(self) -> None:
        result = float(safe_eval("sin(pi/6)"))
        assert abs(result - 0.5) < 1e-10

    def test_cos(self) -> None:
        result = float(safe_eval("cos(0)"))
        assert abs(result - 1.0) < 1e-10

    def test_log10(self) -> None:
        assert safe_eval("log10(1000)") == "3"

    def test_log_with_base(self) -> None:
        assert safe_eval("log(8, 2)") == "3"

    def test_ln(self) -> None:
        result = float(safe_eval("ln(e)"))
        assert abs(result - 1.0) < 1e-10

    def test_factorial(self) -> None:
        assert safe_eval("factorial(10)") == "3628800"

    def test_degrees(self) -> None:
        result = float(safe_eval("degrees(pi)"))
        assert abs(result - 180.0) < 1e-10

    def test_radians(self) -> None:
        result = float(safe_eval("radians(180)"))
        assert abs(result - math.pi) < 1e-8

    def test_ceil(self) -> None:
        assert safe_eval("ceil(3.2)") == "4"

    def test_floor(self) -> None:
        assert safe_eval("floor(3.8)") == "3"

    def test_abs(self) -> None:
        assert safe_eval("abs(-42)") == "42"

    def test_gcd(self) -> None:
        assert safe_eval("gcd(48, 18)") == "6"

    def test_lcm(self) -> None:
        assert safe_eval("lcm(4, 6)") == "12"

    def test_comb(self) -> None:
        assert safe_eval("comb(10, 3)") == "120"

    def test_perm(self) -> None:
        assert safe_eval("perm(5, 3)") == "60"

    def test_factorial_too_large(self) -> None:
        with pytest.raises(ValueError, match="参数过大"):
            safe_eval("factorial(9999)")

    def test_comb_too_large(self) -> None:
        with pytest.raises(ValueError, match="参数过大"):
            safe_eval("comb(9999, 5000)")

    def test_perm_too_large(self) -> None:
        with pytest.raises(ValueError, match="参数过大"):
            safe_eval("perm(9999, 5000)")

    def test_factorial_at_limit(self) -> None:
        """factorial(1000) should succeed (within limit)."""
        result = safe_eval("factorial(1000)")
        assert int(result) > 0

    def test_hypot(self) -> None:
        assert safe_eval("hypot(3, 4)") == "5"


class TestStatistics:
    def test_mean(self) -> None:
        assert safe_eval("mean(1, 2, 3, 4, 5)") == "3"

    def test_median(self) -> None:
        assert safe_eval("median(1, 3, 5, 7, 9)") == "5"

    def test_stdev(self) -> None:
        result = float(safe_eval("stdev(2, 4, 4, 4, 5, 5, 7, 9)"))
        assert result > 0

    def test_min_max(self) -> None:
        assert safe_eval("min(3, 1, 4, 1, 5)") == "1"
        assert safe_eval("max(3, 1, 4, 1, 5)") == "5"

    def test_sum(self) -> None:
        assert safe_eval("sum([1, 2, 3, 4, 5])") == "15"


class TestComparison:
    def test_equal(self) -> None:
        assert safe_eval("2+2 == 4") == "True"

    def test_not_equal(self) -> None:
        assert safe_eval("2+2 != 5") == "True"

    def test_less_than(self) -> None:
        assert safe_eval("3 < 5") == "True"

    def test_greater_than(self) -> None:
        assert safe_eval("5 > 3") == "True"


class TestIfExpression:
    def test_ternary(self) -> None:
        assert safe_eval("42 if 2>1 else 0") == "42"


class TestSafety:
    def test_rejects_import(self) -> None:
        with pytest.raises(ValueError, match="未知函数"):
            safe_eval("__import__('os')")

    def test_rejects_attribute_access(self) -> None:
        with pytest.raises(ValueError, match="不支持"):
            safe_eval("math.pi")

    def test_rejects_unknown_function(self) -> None:
        with pytest.raises(ValueError, match="未知函数"):
            safe_eval("eval('1+1')")

    def test_rejects_unknown_variable(self) -> None:
        with pytest.raises(ValueError, match="未知变量"):
            safe_eval("x + 1")

    def test_rejects_too_large_exponent(self) -> None:
        with pytest.raises(ValueError, match="指数过大"):
            safe_eval("2**100000")

    def test_rejects_too_long_expression(self) -> None:
        with pytest.raises(ValueError, match="表达式过长"):
            safe_eval("1+" * 300 + "1")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="表达式为空"):
            safe_eval("")

    def test_division_by_zero(self) -> None:
        with pytest.raises(ZeroDivisionError):
            safe_eval("1/0")


# ---------------------------------------------------------------------------
# execute() 集成测试
# ---------------------------------------------------------------------------


class TestExecute:
    @pytest.mark.asyncio
    async def test_basic_calculation(self) -> None:
        from Undefined.skills.tools.calculator.handler import execute

        result = await execute({"expression": "2+3*4"}, {})
        assert "= 14" in result

    @pytest.mark.asyncio
    async def test_empty_expression(self) -> None:
        from Undefined.skills.tools.calculator.handler import execute

        result = await execute({"expression": ""}, {})
        assert "请提供" in result

    @pytest.mark.asyncio
    async def test_error_message(self) -> None:
        from Undefined.skills.tools.calculator.handler import execute

        result = await execute({"expression": "1/0"}, {})
        assert "除以零" in result

    @pytest.mark.asyncio
    async def test_syntax_error(self) -> None:
        from Undefined.skills.tools.calculator.handler import execute

        result = await execute({"expression": "2+++"}, {})
        assert "语法错误" in result
