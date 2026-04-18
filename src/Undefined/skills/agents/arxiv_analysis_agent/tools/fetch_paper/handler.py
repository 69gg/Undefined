"""获取 arXiv 论文元数据并下载 PDF 到本地缓存。"""

from __future__ import annotations

import logging
from typing import Any

import fitz

from Undefined.arxiv.client import get_paper_info
from Undefined.arxiv.downloader import download_paper_pdf
from Undefined.arxiv.parser import normalize_arxiv_id

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE_MB = 50


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    raw_id = str(args.get("paper_id", "")).strip()
    if not raw_id:
        return "错误：请提供 arXiv 论文 ID"

    paper_id = normalize_arxiv_id(raw_id) or raw_id

    request_context = {"request_id": context.get("request_id", "-")}

    try:
        paper = await get_paper_info(paper_id, context=request_context)
    except Exception as exc:
        logger.exception("[arxiv_analysis] 获取论文元数据失败: %s", exc)
        return f"错误：获取论文 {paper_id} 元数据失败 — {exc}"

    if paper is None:
        return f"错误：未找到论文 arXiv:{paper_id}"

    lines: list[str] = [
        f"论文: {paper.title}",
        f"ID: {paper.paper_id}",
        f"作者: {'、'.join(paper.authors[:10])}{'（等 ' + str(len(paper.authors)) + ' 位）' if len(paper.authors) > 10 else ''}",
        f"分类: {paper.primary_category}",
        f"发布: {paper.published[:10]}",
        f"更新: {paper.updated[:10]}",
        f"链接: {paper.abs_url}",
        f"\n摘要:\n{paper.summary}",
    ]

    try:
        result, task_dir = await download_paper_pdf(
            paper, max_file_size_mb=_MAX_FILE_SIZE_MB, context=request_context
        )
    except Exception as exc:
        logger.exception("[arxiv_analysis] PDF 下载失败: %s", exc)
        lines.append(f"\nPDF 下载失败: {exc}（可基于摘要进行分析）")
        return "\n".join(lines)

    if result.path is None:
        lines.append(f"\nPDF 不可用（状态: {result.status}），请基于摘要进行分析")
        return "\n".join(lines)

    try:
        doc = fitz.open(str(result.path))
        try:
            page_count = len(doc)
            lines.append(f"\nPDF 已下载: {page_count} 页")
            context["_arxiv_pdf_path"] = str(result.path)
            context["_arxiv_pdf_pages"] = page_count
            context["_arxiv_task_dir"] = str(task_dir)
        finally:
            doc.close()
    except Exception as exc:
        logger.exception("[arxiv_analysis] PDF 打开失败: %s", exc)
        lines.append(f"\nPDF 无法打开: {exc}（可基于摘要进行分析）")

    return "\n".join(lines)
