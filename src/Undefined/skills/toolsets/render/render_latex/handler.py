from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict

from Undefined.attachments import scope_from_context
from Undefined.config import get_config
from Undefined.skills.http_config import get_configured_proxy

logger = logging.getLogger(__name__)

_DOCUMENT_PATTERN = re.compile(
    r"^\s*\\begin\{document\}(?P<body>.*?)\\end\{document\}\s*$",
    re.DOTALL,
)

# MathJax 数学分隔符模式
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


def _build_html(latex_content: str) -> str:
    """构建包含 MathJax 的 HTML 页面。"""
    # HTML 转义（防止内容中的 < > & 破坏结构）
    import html

    escaped_content = html.escape(latex_content)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script>
window.MathJax = {{
  tex: {{ inlineMath: [['$','$'], ['\\\\(','\\\\)']] }},
  startup: {{
    pageReady: function() {{
      return MathJax.startup.defaultPageReady().then(function() {{
        window._mjReady = true;
      }});
    }}
  }}
}};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
<style>
  body {{ margin: 0; padding: 20px; background: white; }}
  #math-container {{ display: inline-block; font-size: 18px; }}
</style>
</head>
<body>
<div id="math-container">
{escaped_content}
</div>
</body>
</html>"""


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


async def _render_latex_to_bytes(
    content: str, output_format: str, proxy: str | None = None
) -> tuple[bytes, str]:
    """
    优先使用本地 mathtext 渲染，复杂内容再回退到 MathJax + Playwright。

    返回: (渲染后的字节流, MIME 类型)
    """
    try:
        return await _render_mathtext_to_bytes(content, output_format)
    except Exception as exc:
        logger.debug("本地 mathtext 渲染失败，回退到 MathJax: %s", exc)

    try:
        from playwright.async_api import (
            Page,
            TimeoutError as PwTimeoutError,
        )
        from Undefined.render import render_html_with_page
    except ImportError:
        raise ImportError(
            "请运行 `uv run playwright install` 安装浏览器运行时"
        ) from None

    html_content = _build_html(content)
    if proxy:
        logger.info("LaTeX 渲染使用代理: %s", proxy)

    async def _render_page(page: Page) -> tuple[bytes, str]:
        # 等待 MathJax 完成排版（pageReady 回调设置 window._mjReady）
        try:
            await page.wait_for_function(
                "() => window._mjReady === true",
                timeout=30000,
            )
        except PwTimeoutError:
            logger.warning("MathJax 排版超时，内容可能过于复杂或网络不可达")
            raise RuntimeError(
                "LaTeX 内容可能过于复杂或网络不可达（MathJax 加载超时）"
            ) from None

        container = await page.query_selector("#math-container")
        if container is None:
            raise RuntimeError("无法定位数学容器元素")

        if output_format == "pdf":
            bbox = await container.bounding_box()
            if bbox is None:
                raise RuntimeError("无法获取数学容器的边界框")

            pdf_bytes = await page.pdf(
                width=f"{bbox['width'] + 40}px",
                height=f"{bbox['height'] + 40}px",
                print_background=True,
            )
            return pdf_bytes, "application/pdf"

        screenshot_bytes = await container.screenshot(type="png")
        return screenshot_bytes, "image/png"

    return await render_html_with_page(html_content, _render_page, proxy=proxy)


async def _resolve_proxy(context: Dict[str, Any]) -> str | None:
    """从 context 的 runtime_config 中解析代理地址。"""
    runtime_config = context.get("runtime_config") or get_config(strict=False)
    if runtime_config is None:
        return None
    return get_configured_proxy(
        "https://cdn.jsdelivr.net",
        use_proxy=bool(getattr(runtime_config, "render_use_proxy", False)),
        config=runtime_config,
    )


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

        # 解析代理
        proxy = await _resolve_proxy(context)

        # 渲染
        rendered_bytes, mime_type = await _render_latex_to_bytes(
            prepared_content, output_format, proxy=proxy
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

    except ImportError as e:
        logger.error("Playwright 导入失败: %s", e)
        return "请运行 `uv run playwright install` 安装浏览器运行时"
    except RuntimeError as e:
        logger.error("LaTeX 渲染运行时错误: %s", e)
        return str(e)
    except Exception as e:
        logger.exception("渲染 LaTeX 失败: %s", e)
        return f"渲染失败：{e}"
