"""arXiv PDF 下载。"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import uuid

from Undefined.arxiv.models import PaperInfo
from Undefined.skills.http_config import get_request_timeout
from Undefined.utils.http_download import (
    cleanup_download_dir,
    download_remote_file,
    probe_remote_file,
)
from Undefined.utils.paths import DOWNLOAD_CACHE_DIR, ensure_dir

logger = logging.getLogger(__name__)

_ARXIV_DOWNLOAD_DIR = DOWNLOAD_CACHE_DIR / "arxiv"


@dataclass(frozen=True)
class PaperDownloadResult:
    path: Path | None
    size_bytes: int | None
    status: str


def build_download_filename(paper_id: str) -> str:
    safe_paper_id = paper_id.replace("/", "_")
    return f"arXiv-{safe_paper_id}.pdf"


async def download_paper_pdf(
    paper: PaperInfo,
    *,
    max_file_size_mb: int,
    context: dict[str, object] | None = None,
) -> tuple[PaperDownloadResult, Path]:
    timeout_seconds = max(get_request_timeout(480.0), 15.0)
    max_file_size_bytes = (
        max_file_size_mb * 1024 * 1024 if max_file_size_mb > 0 else 2**63 - 1
    )
    task_dir = ensure_dir(_ARXIV_DOWNLOAD_DIR / uuid.uuid4().hex)
    file_path = task_dir / build_download_filename(paper.paper_id)

    final_url = paper.pdf_url
    expected_size: int | None = None

    try:
        probe = await probe_remote_file(
            paper.pdf_url,
            timeout_seconds=min(timeout_seconds, 60.0),
            follow_redirects=True,
            context=context,
        )
        final_url = probe.final_url
        expected_size = probe.content_length
        if expected_size is not None and expected_size > max_file_size_bytes:
            logger.info(
                "[arXiv] PDF 超过限制，跳过下载: paper=%s size=%sB limit=%sMB",
                paper.paper_id,
                expected_size,
                max_file_size_mb,
            )
            return PaperDownloadResult(None, expected_size, "too_large"), task_dir
    except Exception as exc:
        logger.warning(
            "[arXiv] PDF 预检失败，转为直接流式下载: paper=%s err=%s",
            paper.paper_id,
            exc,
        )

    try:
        _, downloaded_size = await download_remote_file(
            final_url,
            file_path,
            max_file_size_bytes=max_file_size_bytes,
            timeout_seconds=timeout_seconds,
            expected_size=expected_size,
            follow_redirects=True,
        )
        logger.info(
            "[arXiv] PDF 下载完成: paper=%s size=%sB path=%s",
            paper.paper_id,
            downloaded_size,
            file_path,
        )
        return PaperDownloadResult(file_path, downloaded_size, "downloaded"), task_dir
    except ValueError as exc:
        logger.info(
            "[arXiv] PDF 下载跳过: paper=%s reason=%s",
            paper.paper_id,
            exc,
        )
        return PaperDownloadResult(None, None, "skipped"), task_dir
    except Exception:
        logger.exception("[arXiv] PDF 下载失败: paper=%s", paper.paper_id)
        return PaperDownloadResult(None, None, "failed"), task_dir


async def cleanup_download_path(task_dir: Path) -> None:
    await cleanup_download_dir(task_dir)
