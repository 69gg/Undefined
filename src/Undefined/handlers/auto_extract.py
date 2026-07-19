"""B 站 / 抖音 / arXiv / GitHub 链接自动提取 mixin。

从消息中解析外部资源 ID 并调用对应 sender 发送；由 ``MessageHandler`` 混入使用。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Undefined.config import Config
    from Undefined.onebot import OneBotClient
    from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)


class AutoExtractMixin:
    """外部资源自动提取 mixin。"""

    if TYPE_CHECKING:
        config: Config
        sender: MessageSender
        onebot: OneBotClient

    async def _extract_bilibili_ids(
        self, text: str, message_content: list[dict[str, Any]]
    ) -> list[str]:
        """从文本和消息段中提取 B 站视频 BV 号。"""
        from Undefined.bilibili.parser import (
            extract_bilibili_ids,
            extract_from_json_message,
        )

        bvids = await extract_bilibili_ids(text)
        if not bvids:
            bvids = await extract_from_json_message(message_content)
        return list(bvids)

    def _extract_douyin_ids(
        self, text: str, message_content: list[dict[str, Any]]
    ) -> list[str]:
        """从文本和消息段中提取抖音视频标识。"""
        from Undefined.douyin.parser import (
            extract_douyin_ids,
            extract_from_json_message,
        )

        items: list[str] = []
        seen: set[str] = set()
        for item in extract_douyin_ids(text):
            if item in seen:
                continue
            seen.add(item)
            items.append(item)
        for item in extract_from_json_message(message_content):
            if item in seen:
                continue
            seen.add(item)
            items.append(item)
        return items

    def _extract_arxiv_ids(
        self, text: str, message_content: list[dict[str, Any]]
    ) -> list[str]:
        """从文本和消息段中提取 arXiv 论文 ID。"""
        from Undefined.arxiv.parser import extract_arxiv_ids, extract_from_json_message

        paper_ids: list[str] = []
        seen: set[str] = set()

        for paper_id in extract_arxiv_ids(text):
            if paper_id in seen:
                continue
            seen.add(paper_id)
            paper_ids.append(paper_id)

        for paper_id in extract_from_json_message(message_content):
            if paper_id in seen:
                continue
            seen.add(paper_id)
            paper_ids.append(paper_id)

        return paper_ids

    def _extract_github_repo_ids(
        self, text: str, message_content: list[dict[str, Any]]
    ) -> list[str]:
        """从文本和消息段中提取 GitHub 仓库 ID。"""
        from Undefined.github.parser import (
            extract_from_json_message,
            extract_github_repo_ids,
        )

        repo_ids: list[str] = []
        seen: set[str] = set()

        for repo_id in extract_github_repo_ids(text):
            # 仓库 ID 大小写不敏感去重
            key = repo_id.lower()
            if key in seen:
                continue
            seen.add(key)
            repo_ids.append(repo_id)

        for repo_id in extract_from_json_message(message_content):
            key = repo_id.lower()
            if key in seen:
                continue
            seen.add(key)
            repo_ids.append(repo_id)

        return repo_ids

    async def _handle_bilibili_extract(
        self,
        target_id: int,
        bvids: list[str],
        target_type: str,
        sender: Any | None = None,
    ) -> None:
        """处理 bilibili 视频自动提取和发送。"""
        from Undefined.bilibili.sender import send_bilibili_video

        resolved_sender = sender or self.sender
        for bvid in bvids[:3]:
            try:
                # 单条消息最多自动提取 3 个 BV
                await send_bilibili_video(
                    video_id=bvid,
                    sender=resolved_sender,
                    onebot=self.onebot,
                    target_type=target_type,  # type: ignore[arg-type]
                    target_id=target_id,
                    cookie=self.config.bilibili_cookie,
                    prefer_quality=self.config.bilibili_prefer_quality,
                    max_duration=self.config.bilibili_max_duration,
                    max_file_size=self.config.bilibili_max_file_size,
                    oversize_strategy=self.config.bilibili_oversize_strategy,
                    danmaku_enabled=self.config.bilibili_danmaku_enabled,
                    danmaku_batch_size=self.config.bilibili_danmaku_batch_size,
                    danmaku_max_count=self.config.bilibili_danmaku_max_count,
                )
            except Exception as exc:
                logger.error(
                    "[Bilibili] 自动提取失败 %s → %s:%s: %s",
                    bvid,
                    target_type,
                    target_id,
                    exc,
                )
                try:
                    error_msg = f"视频提取失败: {exc}"
                    if target_type == "group":
                        await resolved_sender.send_group_message(target_id, error_msg)
                    else:
                        await resolved_sender.send_private_message(target_id, error_msg)
                except Exception:
                    pass

    async def _handle_douyin_extract(
        self,
        target_id: int,
        video_ids: list[str],
        target_type: str,
        sender: Any | None = None,
    ) -> None:
        """处理 Douyin 视频自动提取和发送。"""
        from Undefined.douyin.sender import send_douyin_video

        max_items = max(
            1, int(getattr(self.config, "douyin_auto_extract_max_items", 3))
        )
        prefer_ratios = tuple(getattr(self.config, "douyin_prefer_ratios", [])) or (
            "1080p",
            "720p",
            "540p",
            "360p",
        )

        resolved_sender = sender or self.sender
        for video_id in video_ids[:max_items]:
            try:
                result = await send_douyin_video(
                    video_id=video_id,
                    sender=resolved_sender,
                    target_type=target_type,  # type: ignore[arg-type]
                    target_id=target_id,
                    max_duration=self.config.douyin_max_duration,
                    max_file_size=self.config.douyin_max_file_size,
                    prefer_ratios=prefer_ratios,
                    config=self.config,
                )
                logger.info(
                    "[Douyin] 自动提取完成 %s → %s:%s: %s",
                    video_id,
                    target_type,
                    target_id,
                    result,
                )
            except Exception as exc:
                logger.exception(
                    "[Douyin] 自动提取失败 %s → %s:%s",
                    video_id,
                    target_type,
                    target_id,
                )
                try:
                    error_msg = f"抖音视频提取失败: {exc}"
                    if target_type == "group":
                        await resolved_sender.send_group_message(target_id, error_msg)
                    else:
                        await resolved_sender.send_private_message(target_id, error_msg)
                except Exception:
                    pass

    async def _handle_arxiv_extract(
        self,
        target_id: int,
        paper_ids: list[str],
        target_type: str,
        sender: Any | None = None,
    ) -> None:
        """处理 arXiv 论文自动提取和发送。"""
        from Undefined.arxiv.sender import send_arxiv_paper

        max_items = max(1, int(self.config.arxiv_auto_extract_max_items))

        resolved_sender = sender or self.sender
        for paper_id in paper_ids[:max_items]:
            try:
                result = await send_arxiv_paper(
                    paper_id=paper_id,
                    sender=resolved_sender,
                    target_type=target_type,  # type: ignore[arg-type]
                    target_id=target_id,
                    max_file_size=self.config.arxiv_max_file_size,
                    author_preview_limit=self.config.arxiv_author_preview_limit,
                    summary_preview_chars=self.config.arxiv_summary_preview_chars,
                    context={
                        "request_id": (
                            f"arxiv_auto_extract:{target_type}:{target_id}:{paper_id}"
                        )
                    },
                )
                logger.info(
                    "[arXiv] 自动提取完成 %s → %s:%s: %s",
                    paper_id,
                    target_type,
                    target_id,
                    result,
                )
            except Exception:
                logger.exception(
                    "[arXiv] 自动提取失败 %s → %s:%s",
                    paper_id,
                    target_type,
                    target_id,
                )

    async def _handle_github_extract(
        self,
        target_id: int,
        repo_ids: list[str],
        target_type: str,
        sender: Any | None = None,
    ) -> None:
        """处理 GitHub 仓库自动提取和发送。"""
        from Undefined.github.client import (
            DEFAULT_REQUEST_RETRIES,
            DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        from Undefined.github.sender import send_github_repo_card

        max_items = max(
            1, int(getattr(self.config, "github_auto_extract_max_items", 3))
        )
        request_timeout = float(
            getattr(
                self.config,
                "github_request_timeout_seconds",
                DEFAULT_REQUEST_TIMEOUT_SECONDS,
            )
        )
        request_retries = int(
            getattr(self.config, "github_request_retries", DEFAULT_REQUEST_RETRIES)
        )

        resolved_sender = sender or self.sender
        for repo_id in repo_ids[:max_items]:
            try:
                result = await send_github_repo_card(
                    repo_id=repo_id,
                    sender=resolved_sender,
                    target_type=target_type,  # type: ignore[arg-type]
                    target_id=target_id,
                    request_timeout=request_timeout,
                    request_retries=request_retries,
                    context={
                        "request_id": (
                            f"github_auto_extract:{target_type}:{target_id}:{repo_id}"
                        )
                    },
                )
                logger.info(
                    "[GitHub] 自动提取完成 %s → %s:%s: %s",
                    repo_id,
                    target_type,
                    target_id,
                    result,
                )
            except Exception as exc:
                logger.exception(
                    "[GitHub] 自动提取跳过 %s → %s:%s: exc_type=%s exc=%r",
                    repo_id,
                    target_type,
                    target_id,
                    type(exc).__name__,
                    exc,
                )
