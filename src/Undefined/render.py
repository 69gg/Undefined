import markdown
import asyncio
from playwright.async_api import async_playwright

from typing import Any


async def render_markdown_to_html(md_text: str) -> str:
    # 定义同步的解析逻辑
    def _parse() -> str:
        extensions = [
            "toc",
            "tables",
            "fenced_code",
            "codehilite",
            "md_in_html",
            "attr_list",
            "pymdownx.superfences",
            "pymdownx.arithmatex",
            "pymdownx.tasklist",
            "pymdownx.tilde",
            "pymdownx.emoji",
        ]

        extension_configs: dict[str, dict[str, Any]] = {
            "pymdownx.superfences": {
                "custom_fences": [
                    {
                        "name": "mermaid",
                        "class": "mermaid",
                        "format": lambda source,
                        language,
                        css_class,
                        options,
                        md,
                        **kwargs: f'<pre class="{css_class}">{source}</pre>',
                    }
                ]
            },
            "pymdownx.arithmatex": {
                "generic": True,
            },
        }

        return str(
            markdown.markdown(
                md_text, extensions=extensions, extension_configs=extension_configs
            )
        )

    # 使用 to_thread 在独立的线程中运行同步的 markdown 解析，避免阻塞主循环
    html_content = await asyncio.to_thread(_parse)

    # 拼接 HTML 模板（这部分是纯字符串操作，速度极快，无需放进线程）
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.2.0/github-markdown.min.css">
        <style>
            body {{ background-color: white; padding: 45px; }}
            .markdown-body {{ box-sizing: border-box; min-width: 200px; max-width: 980px; margin: 0 auto; }}
            .mermaid {{ background: transparent !important; border: none !important; }}
        </style>
        <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
        <script>
        window.MathJax = {{
          tex: {{ inlineMath: [['$', '$'], ['\\\\(', '\\\\)']] }}
        }};
        </script>
        <script src="https://cdn.jsdelivr.net/npm/mermaid@11.1.0/dist/mermaid.min.js"></script>
    </head>
    <body>
        <article class="markdown-body">
            {html_content}
        </article>
        <script>
            mermaid.initialize({{
                startOnLoad: true,
                theme: 'default',
                securityLevel: 'loose',
                fontFamily: 'arial'
            }});
        </script>
    </body>
    </html>
    """
    return full_html


async def render_html_to_image(html_content: str, output_path: str) -> None:
    """
    将 HTML 字符串转换为 PNG 图片

    参数:
        html_content: 完整的 HTML 字符串
        output_path: 输出图片路径 (例如 'result.png')
    """
    async with async_playwright() as p:
        # 启动无头浏览器
        browser = await p.chromium.launch(headless=True)
        # 设置上下文，可以指定缩放比例(device_scale_factor)，2代表2倍清晰度(Retina)
        context = await browser.new_context(device_scale_factor=2)
        page = await context.new_page()

        # 设置页面内容
        await page.set_content(html_content)

        # --- 关键：等待渲染完成 ---
        # 1. 等待网络空闲（确保 CDN 上的 MathJax/Mermaid 脚本加载完）
        await page.wait_for_load_state("networkidle")

        # 2. 如果有 Mermaid，给它一点时间执行 JS 绘图
        # 如果页面里没有 mermaid 脚本，这行会很快跳过
        await asyncio.sleep(1)  # 等待 1 秒钟让 Mermaid 渲染完成

        # 3. 自动调整视口大小以匹配内容
        # 如果你想截取整个页面，使用 full_page=True
        # 如果只想截取特定容器，可以定位 element = page.locator(".container")
        await page.screenshot(path=output_path, full_page=True)

        await browser.close()
