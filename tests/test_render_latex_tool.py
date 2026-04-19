"""测试 LaTeX 渲染工具（MathJax + Playwright 实现）"""

from __future__ import annotations

import pytest
from typing import Any

# 这个测试需要 Playwright 浏览器运行时，所以标记为可选
pytest_plugins = ("pytest_asyncio",)


class MockAttachmentRegistry:
    """模拟附件注册表"""

    def __init__(self) -> None:
        self.registered_items: list[dict[str, Any]] = []

    async def register_bytes(
        self,
        scope_key: str,
        data: bytes,
        kind: str,
        display_name: str,
        mime_type: str,
        source_kind: str,
        source_ref: str,
    ) -> Any:
        class MockRecord:
            uid = "test-uid-12345"

        record = MockRecord()
        self.registered_items.append(
            {
                "scope_key": scope_key,
                "size": len(data),
                "kind": kind,
                "display_name": display_name,
                "mime_type": mime_type,
                "source_kind": source_kind,
                "source_ref": source_ref,
                "uid": record.uid,
            }
        )
        return record


@pytest.mark.asyncio
async def test_render_simple_equation() -> None:
    """测试渲染简单方程（无分隔符，自动包装）"""
    from Undefined.skills.toolsets.render.render_latex.handler import execute

    mock_registry = MockAttachmentRegistry()
    context = {
        "attachment_registry": mock_registry,
        "request_type": "group",
        "group_id": 123456,
    }

    args = {"content": "E = mc^2", "output_format": "png"}

    result = await execute(args, context)
    if "渲染失败" in result and "Executable doesn't exist" in result:
        pytest.skip("Playwright 浏览器未安装，跳过测试")
    assert result == '<pic uid="test-uid-12345"/>'
    assert len(mock_registry.registered_items) == 1
    assert mock_registry.registered_items[0]["kind"] == "image"
    assert mock_registry.registered_items[0]["mime_type"] == "image/png"
    assert mock_registry.registered_items[0]["size"] > 0


@pytest.mark.asyncio
async def test_render_with_delimiters() -> None:
    """测试带分隔符的内容（不自动包装）"""
    from Undefined.skills.toolsets.render.render_latex.handler import execute

    mock_registry = MockAttachmentRegistry()
    context = {
        "attachment_registry": mock_registry,
        "request_type": "private",
        "user_id": 987654,
    }

    args = {"content": r"\[ \int_0^\infty e^{-x^2} dx = \frac{\sqrt{\pi}}{2} \]"}

    result = await execute(args, context)
    if "渲染失败" in result and "Executable doesn't exist" in result:
        pytest.skip("Playwright 浏览器未安装，跳过测试")
    assert result == '<pic uid="test-uid-12345"/>'
    assert len(mock_registry.registered_items) == 1


@pytest.mark.asyncio
async def test_render_pdf_output() -> None:
    """测试 PDF 输出格式使用 attachment 标签"""
    from Undefined.skills.toolsets.render.render_latex.handler import execute

    mock_registry = MockAttachmentRegistry()
    context = {
        "attachment_registry": mock_registry,
        "request_type": "group",
        "group_id": 123456,
    }

    args = {"content": r"\frac{a}{b} + \sqrt{c}", "output_format": "pdf"}

    result = await execute(args, context)
    if "渲染失败" in result and "Executable doesn't exist" in result:
        pytest.skip("Playwright 浏览器未安装，跳过测试")
    assert result == '<attachment uid="test-uid-12345"/>'
    assert len(mock_registry.registered_items) == 1
    assert mock_registry.registered_items[0]["kind"] == "file"
    assert mock_registry.registered_items[0]["mime_type"] == "application/pdf"
    assert mock_registry.registered_items[0]["display_name"] == "latex.pdf"


@pytest.mark.asyncio
async def test_empty_content_error() -> None:
    """测试空内容错误处理"""
    from Undefined.skills.toolsets.render.render_latex.handler import execute

    context = {"attachment_registry": MockAttachmentRegistry()}

    args = {"content": "   "}

    result = await execute(args, context)
    assert "不能为空" in result


@pytest.mark.asyncio
async def test_invalid_output_format() -> None:
    """测试无效输出格式"""
    from Undefined.skills.toolsets.render.render_latex.handler import execute

    context = {"attachment_registry": MockAttachmentRegistry()}

    args = {"content": "x = 1", "output_format": "svg"}

    result = await execute(args, context)
    assert "无效" in result or "仅支持" in result


def test_strip_document_wrappers() -> None:
    """测试去除 document 包装"""
    from Undefined.skills.toolsets.render.render_latex.handler import (
        _strip_document_wrappers,
    )

    content = r"\begin{document}E = mc^2\end{document}"
    result = _strip_document_wrappers(content)
    assert result == "E = mc^2"

    # 没有包装的内容应该原样返回
    content_no_wrapper = r"E = mc^2"
    result_no_wrapper = _strip_document_wrappers(content_no_wrapper)
    assert result_no_wrapper == "E = mc^2"


def test_has_math_delimiters() -> None:
    """测试数学分隔符检测"""
    from Undefined.skills.toolsets.render.render_latex.handler import (
        _has_math_delimiters,
    )

    assert _has_math_delimiters(r"\[ x = 1 \]") is True
    assert _has_math_delimiters(r"\( x = 1 \)") is True
    assert _has_math_delimiters(r"$$ x = 1 $$") is True
    assert _has_math_delimiters(r"\begin{equation}") is True
    assert _has_math_delimiters("x = 1") is False


def test_prepare_content() -> None:
    """测试内容准备逻辑"""
    from Undefined.skills.toolsets.render.render_latex.handler import _prepare_content

    # 无分隔符，自动包装
    result = _prepare_content("E = mc^2")
    assert result.startswith(r"\[")
    assert result.endswith(r"\]")
    assert "E = mc^2" in result

    # 有分隔符，不包装
    result_with_delim = _prepare_content(r"\[ E = mc^2 \]")
    assert result_with_delim == r"\[ E = mc^2 \]"

    # 字面量 \\n 处理（后面不跟字母时替换为换行）
    result_newline = _prepare_content("x = 1\\n2 = y")
    assert "\n" in result_newline
    assert "x = 1" in result_newline
    assert "2 = y" in result_newline

    # LaTeX 命令不被破坏：\nu \nabla \neq 保持不变
    result_latex = _prepare_content(r"\nu + \nabla \neq 0")
    assert r"\nu" in result_latex
    assert r"\nabla" in result_latex
    assert r"\neq" in result_latex


def test_build_html_contains_mathjax_ready_flag() -> None:
    """HTML 模板包含 MathJax pageReady 回调设置 _mjReady 标记"""
    from Undefined.skills.toolsets.render.render_latex.handler import _build_html

    html = _build_html(r"\[ x = 1 \]")
    assert "window._mjReady = true" in html
    assert "pageReady" in html
    assert "tex-svg.js" in html
    assert "math-container" in html
