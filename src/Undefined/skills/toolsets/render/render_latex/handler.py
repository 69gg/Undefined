from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict

from Undefined.attachments import scope_from_context

logger = logging.getLogger(__name__)

_DOCUMENT_PATTERN = re.compile(
    r"^\s*\\begin\{document\}(?P<body>.*?)\\end\{document\}\s*$",
    re.DOTALL,
)

# 数学分隔符模式
_MATH_DELIMITER_PATTERN = re.compile(
    r"(\$\$|\\\[|\\\(|\\begin\{)",
    re.MULTILINE,
)


def _strip_document_wrappers(content: str) -> str:
    """去掉 \\begin{document}...\\end{document} 外层包装。"""
    text = content.strip()
    match = _DOCUMENT_PATTERN.fullmatch(text)
    if match is None:
        return text
    return match.group("body").strip()


def _has_math_delimiters(content: str) -> bool:
    """检查内容是否已包含数学分隔符。"""
    return bool(_MATH_DELIMITER_PATTERN.search(content))


def _prepare_content(raw_content: str) -> str:
    """
    准备 LaTeX 内容：
    1. 去掉 document 包装
    2. 处理字面量 \\n（LLM 输出常见问题）
    3. 如果没有数学分隔符，自动用 \\[ ... \\] 包装
    """
    content = _strip_document_wrappers(raw_content)
    # 替换字面量 \\n 为真实换行符，但保留 LaTeX 命令如 \nu \nabla \neq 等
    content = re.sub(r"\\n(?![a-zA-Z])", "\n", content)

    if not _has_math_delimiters(content):
        # 没有分隔符，自动包装为块级数学环境
        content = f"\\[\n{content}\n\\]"

    return content


def _strip_math_wrappers(content: str) -> str:
    """去掉 mathtext 可直接处理的外层数学分隔符。"""
    text = content.strip()
    wrapper_patterns = (
        r"^\\\[(?P<body>.*?)\\\]$",
        r"^\\\((?P<body>.*?)\\\)$",
        r"^\$\$(?P<body>.*?)\$\$$",
        r"^\$(?P<body>.*?)\$$",
        r"^\\begin\{equation\*?\}(?P<body>.*?)\\end\{equation\*?\}$",
    )
    for pattern in wrapper_patterns:
        match = re.fullmatch(pattern, text, re.DOTALL)
        if match is not None:
            return match.group("body").strip()
    return text


def _render_mathtext_sync(content: str, output_format: str) -> tuple[bytes, str]:
    """使用 matplotlib mathtext 在本地渲染常见数学公式。"""
    import io

    from matplotlib import mathtext
    from matplotlib.font_manager import FontProperties

    expression = _strip_math_wrappers(content)
    if not expression or "\\begin{" in expression:
        raise RuntimeError("内容不是 mathtext 可直接渲染的简单公式")

    font_properties = FontProperties(size=18)
    buffer = io.BytesIO()
    if output_format == "pdf":
        mathtext.math_to_image(
            f"${expression}$",
            buffer,
            prop=font_properties,
            dpi=200,
            format="pdf",
        )
        return buffer.getvalue(), "application/pdf"

    mathtext.math_to_image(
        f"${expression}$",
        buffer,
        prop=font_properties,
        dpi=200,
        format="png",
    )
    return buffer.getvalue(), "image/png"


async def _render_mathtext_to_bytes(
    content: str, output_format: str
) -> tuple[bytes, str]:
    return await asyncio.to_thread(_render_mathtext_sync, content, output_format)


async def _render_latex_to_bytes(content: str, output_format: str) -> tuple[bytes, str]:
    """使用本地 mathtext 渲染，返回字节流及 MIME 类型。"""
    try:
        return await _render_mathtext_to_bytes(content, output_format)
    except Exception as exc:
        logger.debug("本地 mathtext 渲染失败: %s", exc)
        raise RuntimeError(
            "LaTeX 内容超出本地 mathtext 支持范围；渲染沙箱已禁用外部网络"
        ) from exc


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """渲染 LaTeX 数学公式为图片或 PDF"""
    raw_content = str(args.get("content", "") or "")
    output_format = str(args.get("output_format", "png") or "png").strip().lower()

    # 参数校验
    if not raw_content or not raw_content.strip():
        return "LaTeX 内容不能为空"

    if output_format not in {"png", "pdf"}:
        return f"output_format 无效：{output_format}。仅支持 png 或 pdf"

    try:
        # 准备内容
        prepared_content = _prepare_content(raw_content)

        # 渲染
        rendered_bytes, mime_type = await _render_latex_to_bytes(
            prepared_content, output_format
        )

        # 注册到附件系统
        attachment_registry = context.get("attachment_registry")
        scope_key = scope_from_context(context)

        if attachment_registry is None or not scope_key:
            return "渲染成功，但无法注册到附件系统（缺少 attachment_registry 或 scope_key）"

        kind = "image" if output_format == "png" else "file"
        extension = "png" if output_format == "png" else "pdf"
        display_name = f"latex.{extension}"

        try:
            record = await attachment_registry.register_bytes(
                scope_key,
                rendered_bytes,
                kind=kind,
                display_name=display_name,
                mime_type=mime_type,
                source_kind="rendered_latex",
                source_ref="render_latex",
            )
            return f'<attachment uid="{record.uid}"/>'

        except Exception as exc:
            logger.exception("注册渲染结果到附件系统失败: %s", exc)
            return f"渲染成功，但注册到附件系统失败: {exc}"

    except RuntimeError as e:
        logger.error("LaTeX 渲染运行时错误: %s", e)
        return str(e)
    except Exception as e:
        logger.exception("渲染 LaTeX 失败: %s", e)
        return f"渲染失败：{e}"
