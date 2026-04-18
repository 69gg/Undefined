from __future__ import annotations

import logging
import re
from typing import Any, Dict

from Undefined.attachments import scope_from_context

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
    # 替换字面量 \\n 为真实换行符
    content = content.replace("\\n", "\n")

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


async def _render_latex_to_bytes(
    content: str, output_format: str, proxy: str | None = None
) -> tuple[bytes, str]:
    """
    使用 MathJax + Playwright 渲染 LaTeX 内容。

    返回: (渲染后的字节流, MIME 类型)
    """
    try:
        from playwright.async_api import (
            async_playwright,
            TimeoutError as PwTimeoutError,
        )
    except ImportError:
        raise ImportError(
            "请运行 `uv run playwright install` 安装浏览器运行时"
        ) from None

    html_content = _build_html(content)

    launch_kwargs: dict[str, object] = {"headless": True}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}
        logger.info("LaTeX 渲染使用代理: %s", proxy)

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_kwargs)  # type: ignore[arg-type]
        try:
            page = await browser.new_page()
            await page.set_content(html_content)

            # 等待 MathJax 完成排版
            try:
                await page.wait_for_function(
                    "() => window.MathJax?.startup?.promise?.then(() => true) ?? false",
                    timeout=15000,
                )
            except PwTimeoutError:
                logger.warning("MathJax 排版超时，内容可能过于复杂或网络不可达")
                raise RuntimeError(
                    "LaTeX 内容可能过于复杂或网络不可达（MathJax 加载超时）"
                ) from None

            if output_format == "pdf":
                # 获取容器尺寸
                container = await page.query_selector("#math-container")
                if container is None:
                    raise RuntimeError("无法定位数学容器元素")

                bbox = await container.bounding_box()
                if bbox is None:
                    raise RuntimeError("无法获取数学容器的边界框")

                # PDF 输出，设置合适的页面尺寸
                pdf_bytes = await page.pdf(
                    width=f"{bbox['width'] + 40}px",
                    height=f"{bbox['height'] + 40}px",
                    print_background=True,
                )
                return pdf_bytes, "application/pdf"
            else:
                # PNG 输出
                container = await page.query_selector("#math-container")
                if container is None:
                    raise RuntimeError("无法定位数学容器元素")

                screenshot_bytes = await container.screenshot(type="png")
                return screenshot_bytes, "image/png"

        finally:
            await browser.close()


async def _resolve_proxy(context: Dict[str, Any]) -> str | None:
    """从 context 的 runtime_config 中解析代理地址。"""
    from Undefined.config import get_config

    runtime_config = context.get("runtime_config") or get_config(strict=False)
    if runtime_config is None:
        return None
    use_proxy: bool = getattr(runtime_config, "use_proxy", False)
    if not use_proxy:
        return None
    proxy: str = getattr(runtime_config, "http_proxy", "") or getattr(
        runtime_config, "https_proxy", ""
    )
    return proxy or None


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
            tag = "pic" if output_format == "png" else "attachment"
            return f'<{tag} uid="{record.uid}"/>'

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
