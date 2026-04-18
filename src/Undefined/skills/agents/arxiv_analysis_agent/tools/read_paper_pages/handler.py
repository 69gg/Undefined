"""分页读取已下载的 arXiv 论文 PDF 文本。"""

from __future__ import annotations

import logging
from typing import Any

import fitz

logger = logging.getLogger(__name__)

_MAX_CHARS_PER_READ = 15000


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    pdf_path = context.get("_arxiv_pdf_path")
    total_pages = context.get("_arxiv_pdf_pages")

    if not pdf_path:
        return "错误：请先调用 fetch_paper 下载论文"

    try:
        start_page = int(args.get("start_page", 1))
        end_page = int(args.get("end_page", start_page))
    except (TypeError, ValueError):
        return "错误：页码必须为整数"

    if start_page < 1:
        start_page = 1
    if total_pages and end_page > total_pages:
        end_page = total_pages
    if start_page > end_page:
        return f"错误：起始页 {start_page} 大于结束页 {end_page}"

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        logger.exception("[arxiv_analysis] PDF 打开失败: %s", exc)
        return f"错误：PDF 文件无法打开 — {exc}"

    try:
        actual_pages = len(doc)
        if start_page > actual_pages:
            return f"错误：论文共 {actual_pages} 页，请求的起始页 {start_page} 超出范围"

        end_page = min(end_page, actual_pages)
        text_parts: list[str] = []
        total_chars = 0

        for page_num in range(start_page - 1, end_page):
            page = doc.load_page(page_num)
            raw_text = page.get_text()
            page_text = str(raw_text) if raw_text else ""

            if total_chars + len(page_text) > _MAX_CHARS_PER_READ and text_parts:
                text_parts.append(
                    f"\n[第 {page_num + 1} 页起文本已截断，请用更小的页范围重新读取]"
                )
                break

            text_parts.append(f"--- 第 {page_num + 1} 页 ---")
            text_parts.append(page_text if page_text.strip() else "(此页无可提取文本)")
            total_chars += len(page_text)

        header = f"论文内容（第 {start_page}-{end_page} 页，共 {actual_pages} 页）"
        return f"{header}\n\n" + "\n".join(text_parts)
    finally:
        doc.close()
