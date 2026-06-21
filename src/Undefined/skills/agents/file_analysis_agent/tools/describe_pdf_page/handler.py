from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import fitz

from Undefined.skills.agents.file_analysis_agent.tools.analyze_multimodal import (
    handler as analyze_multimodal_handler,
)
from Undefined.utils.paths import ensure_dir

logger = logging.getLogger(__name__)

_MAX_PAGES_PER_CALL = 5
_DEFAULT_DPI = 150


def _parse_page_range(value: str, page_count: int) -> tuple[list[int], str | None]:
    text = str(value or "").strip()
    if not text:
        return [], "错误：page_range 不能为空"

    pages: list[int] = []
    seen: set[int] = set()
    for raw_part in text.split(","):
        part = raw_part.strip()
        if not part:
            return [], f"错误：页码范围格式无效：{value}"
        if "-" in part:
            start_text, sep, end_text = part.partition("-")
            if not sep or not start_text.strip() or not end_text.strip():
                return [], f"错误：页码范围格式无效：{value}"
            try:
                start = int(start_text)
                end = int(end_text)
            except ValueError:
                return [], f"错误：页码范围格式无效：{value}"
            if start > end:
                return [], f"错误：页码范围起始页不能大于结束页：{part}"
            candidates = range(start, end + 1)
        else:
            try:
                page = int(part)
            except ValueError:
                return [], f"错误：页码范围格式无效：{value}"
            candidates = range(page, page + 1)

        for page in candidates:
            if page < 1 or page > page_count:
                return [], f"错误：页码 {page} 超出范围，PDF 共 {page_count} 页"
            if page not in seen:
                pages.append(page)
                seen.add(page)

    if len(pages) > _MAX_PAGES_PER_CALL:
        return (
            [],
            f"错误：单次最多分析 {_MAX_PAGES_PER_CALL} 页，请缩小 page_range",
        )
    return pages, None


def _render_page_to_png(doc: fitz.Document, page_number: int, output_dir: Path) -> Path:
    page = doc.load_page(page_number - 1)
    pix = page.get_pixmap(dpi=_DEFAULT_DPI)
    output_path = output_dir / f"pdf_page_{page_number}_{uuid4().hex[:8]}.png"
    pix.save(str(output_path))
    return output_path


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    file_path = str(args.get("file_path", "") or "").strip()
    page_range = str(args.get("page_range", "") or "").strip()
    prompt = str(args.get("prompt", "") or "").strip()
    force_analyze = bool(args.get("force_analyze", False))

    if not file_path:
        return "错误：file_path 不能为空"

    path = Path(file_path)
    if not path.exists():
        return f"错误：文件不存在 {file_path}"
    if not path.is_file():
        return f"错误：{file_path} 不是文件"

    temp_root_raw = context.get("download_cache_dir")
    if temp_root_raw:
        output_dir = ensure_dir(Path(temp_root_raw) / "pdf_pages" / uuid4().hex[:16])
    else:
        output_dir = ensure_dir(path.parent / ".pdf_pages" / uuid4().hex[:16])

    rendered_paths: list[Path] = []
    try:
        doc = fitz.open(str(path))
        try:
            page_count = len(doc)
            pages, error = _parse_page_range(page_range, page_count)
            if error:
                return error

            results: list[str] = [
                f"PDF 共 {page_count} 页，本次视觉分析页码："
                f"{', '.join(str(page) for page in pages)}"
            ]
            for page_number in pages:
                rendered = _render_page_to_png(doc, page_number, output_dir)
                rendered_paths.append(rendered)
                page_prompt = prompt or "请描述这一页 PDF 的视觉内容。"
                analysis = await analyze_multimodal_handler.execute(
                    {
                        "file_path": str(rendered),
                        "media_type": "image",
                        "prompt": page_prompt,
                        "force_analyze": force_analyze,
                    },
                    context,
                )
                results.append(f"\n--- 第 {page_number} 页 ---\n{analysis}")
            return "\n".join(results)
        finally:
            doc.close()
    except Exception as exc:
        logger.exception("PDF 页面视觉分析失败: %s", exc)
        return "PDF 页面视觉分析失败，文件可能已损坏、加密或无法渲染"
    finally:
        for rendered in rendered_paths:
            try:
                rendered.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            output_dir.rmdir()
            parent = output_dir.parent
            if parent.name == "pdf_pages" and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass
