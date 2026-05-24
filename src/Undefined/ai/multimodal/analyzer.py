"""多模态媒体分析器实现。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import aiofiles
import httpx

from Undefined.ai.llm import ModelRequester
import Undefined.ai.multimodal as _multimodal_pkg
from Undefined.ai.multimodal.constants import (
    ERROR_MESSAGES,
    HISTORY_FILE_PATH,
    MAX_QA_HISTORY,
    MEDIA_TYPE_TO_FIELD,
    MEME_DESCRIBE_PROMPT_PATH,
    MEME_DESCRIBE_TOOL,
    MEME_JUDGE_PROMPT_PATH,
    MEME_JUDGE_TOOL,
)
from Undefined.ai.multimodal.detection import detect_media_type, get_media_mime_type
from Undefined.ai.multimodal.parsing import (
    _normalize_meme_tags,
    _parse_analysis_response,
)
from Undefined.ai.parsing import extract_choices_content
from Undefined.ai.transports import API_MODE_CHAT_COMPLETIONS, get_api_mode
from Undefined.config import VisionModelConfig
from Undefined.utils.coerce import safe_float
from Undefined.utils.logging import log_debug_json, redact_string
from Undefined.utils.resources import read_text_resource
from Undefined.utils.tool_calls import extract_required_tool_call_arguments

logger = logging.getLogger(__name__)


class MultimodalAnalyzer:
    """多模态媒体分析器。

    支持分析图片、音频和视频文件，提取描述内容和类型特定信息（如 OCR 文字、转写文字、字幕等）。
    """

    def __init__(
        self,
        requester: ModelRequester,
        vision_config: VisionModelConfig,
        prompt_path: str = "res/prompts/analyze_multimodal.txt",
    ) -> None:
        """初始化多模态分析器。

        Args:
            requester: 模型请求器
            vision_config: 视觉模型配置
            prompt_path: 提示词模板文件路径
        """
        self._requester = requester
        self._vision_config = vision_config
        self._prompt_path = prompt_path
        self._cache: dict[str, dict[str, str]] = {}
        # 按文件名索引的 Q&A 历史：{filename: [{q: ..., a: ...}, ...]}
        self._file_history: dict[str, list[dict[str, str]]] = {}

        # URL 下载锁：按 URL 哈希粒度加锁，避免并发下载同一文件造成竞态。
        # URL download lock: keyed by URL hash to avoid duplicate concurrent downloads.
        self._url_cache_locks: dict[str, asyncio.Lock] = {}
        self._url_cache_locks_guard = asyncio.Lock()

        # 缓存清理锁 + 上次清理时间，避免并发清理相互干扰。
        # Cache cleanup lock + last cleanup timestamp to avoid concurrent cleanup races.
        self._url_cache_cleanup_lock = asyncio.Lock()
        self._last_url_cache_cleanup_at = 0.0

        self._load_history()

    async def _load_media_content(self, media_url: str, media_type: str) -> str:
        """加载媒体内容。

        如果是本地文件，会将其转换为 base64 编码的 data URL。

        Args:
            media_url: 媒体 URL 或本地文件路径
            media_type: 媒体类型

        Returns:
            可用于 API 请求的媒体内容字符串
        """
        if media_url.startswith("data:"):
            return media_url

        if media_url.startswith("http://") or media_url.startswith("https://"):
            return await self._load_remote_media_as_data_url(media_url, media_type)

        # 读取本地文件并转换为 base64
        async with aiofiles.open(media_url, "rb") as f:
            media_bytes = bytes(await f.read())
        media_data = base64.b64encode(media_bytes).decode()
        mime_type = get_media_mime_type(media_type, media_url)
        return f"data:{mime_type};base64,{media_data}"

    async def _load_remote_media_as_data_url(
        self, media_url: str, media_type: str
    ) -> str:
        """将远程 URL 下载到缓存并转换为 data URL。"""
        cache_key = self._build_url_cache_key(media_url)
        lock = await self._get_url_cache_lock(cache_key)
        cache_path = self._build_url_cache_path(cache_key, media_url)

        async with lock:
            await self._cleanup_url_cache_if_needed()
            if not cache_path.exists():
                await self._download_url_to_cache(media_url, cache_path)
            async with aiofiles.open(cache_path, "rb") as f:
                media_bytes = bytes(await f.read())
            media_data = base64.b64encode(media_bytes).decode()

        mime_type = get_media_mime_type(media_type, media_url)
        return f"data:{mime_type};base64,{media_data}"

    def _build_url_cache_key(self, media_url: str) -> str:
        """构建 URL 缓存键（使用 URL 内容哈希）。"""
        return hashlib.sha256(media_url.encode("utf-8")).hexdigest()

    def _build_url_cache_path(self, cache_key: str, media_url: str) -> Path:
        """基于 URL 生成缓存文件路径。"""
        suffix = Path(urlsplit(media_url).path).suffix.lower()
        if not suffix or len(suffix) > 10:
            suffix = ".bin"
        return _multimodal_pkg._MEDIA_URL_CACHE_DIR / f"{cache_key}{suffix}"

    async def _get_url_cache_lock(self, cache_key: str) -> asyncio.Lock:
        """获取 URL 对应的下载锁（同 URL 串行化）。"""
        async with self._url_cache_locks_guard:
            lock = self._url_cache_locks.get(cache_key)
            if lock is None:
                lock = asyncio.Lock()
                self._url_cache_locks[cache_key] = lock
            return lock

    async def _download_url_to_cache(self, media_url: str, cache_path: Path) -> None:
        """下载远程 URL 到缓存文件（原子写入，避免部分文件）。"""
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_name(
            f"{cache_path.name}{_multimodal_pkg._MEDIA_URL_DOWNLOAD_TMP_SUFFIX}"
        )
        try:
            timeout = httpx.Timeout(_multimodal_pkg._MEDIA_URL_DOWNLOAD_TIMEOUT_SECONDS)
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True
            ) as client:
                response = await client.get(media_url)
                response.raise_for_status()
                async with aiofiles.open(tmp_path, "wb") as f:
                    await f.write(response.content)
            tmp_path.replace(cache_path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise

    @staticmethod
    def _extract_cache_key_from_tmp(path: Path) -> str:
        """从临时文件名提取 cache_key（{key}.{ext}.<tmp_suffix> -> key）。

        Extract cache_key from tmp filename ({key}.{ext}.<tmp_suffix> -> key).
        """
        return Path(path.stem).stem

    @staticmethod
    def _is_download_tmp_path(path: Path) -> bool:
        """判断是否为下载过程临时文件（{key}.{ext}.<tmp_suffix>）。

        Identify download tmp files by requiring a dedicated trailing suffix and
        at least one original extension segment before it.
        """
        suffixes = path.suffixes
        return (
            len(suffixes) >= 2
            and suffixes[-1] == _multimodal_pkg._MEDIA_URL_DOWNLOAD_TMP_SUFFIX
        )

    async def _cleanup_url_cache_if_needed(self) -> None:
        """按 TTL + 文件数上限清理 URL 媒体缓存。"""
        now = time.time()
        if (
            now - self._last_url_cache_cleanup_at
            < _multimodal_pkg._MEDIA_URL_CACHE_CLEANUP_INTERVAL_SECONDS
        ):
            return

        async with self._url_cache_cleanup_lock:
            # 双重检查，避免并发情况下重复清理。
            # Double-check to avoid repeated cleanup under concurrency.
            now = time.time()
            if (
                now - self._last_url_cache_cleanup_at
                < _multimodal_pkg._MEDIA_URL_CACHE_CLEANUP_INTERVAL_SECONDS
            ):
                return
            self._last_url_cache_cleanup_at = now

            async with self._url_cache_locks_guard:
                active_keys = {
                    key for key, lock in self._url_cache_locks.items() if lock.locked()
                }
            cache_dir = _multimodal_pkg._MEDIA_URL_CACHE_DIR
            if not cache_dir.exists():
                await self._prune_url_cache_locks(
                    active_keys=active_keys,
                    present_keys=set(),
                )
                return

            files: list[Path] = [p for p in cache_dir.iterdir() if p.is_file()]
            expire_before = now - _multimodal_pkg._MEDIA_URL_CACHE_TTL_SECONDS
            kept_files: list[Path] = []
            present_keys: set[str] = set()

            # 先按 TTL 清理，跳过正在下载/读取的活跃键。
            # First, TTL cleanup; skip active keys still being downloaded/read.
            for path in files:
                if self._is_download_tmp_path(path):
                    tmp_key = self._extract_cache_key_from_tmp(path)
                    if tmp_key and tmp_key not in active_keys:
                        path.unlink(missing_ok=True)
                    continue
                present_keys.add(path.stem)
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if mtime < expire_before and path.stem not in active_keys:
                    path.unlink(missing_ok=True)
                else:
                    kept_files.append(path)

            await self._prune_url_cache_locks(
                active_keys=active_keys,
                present_keys=present_keys,
            )

            # 再按数量上限清理最旧文件，同样跳过活跃键。
            # Then enforce max-file limit by deleting oldest files, skipping active keys.
            if len(kept_files) <= _multimodal_pkg._MEDIA_URL_CACHE_MAX_FILES:
                return

            kept_with_mtime: list[tuple[float, Path]] = []
            for path in kept_files:
                try:
                    kept_with_mtime.append((path.stat().st_mtime, path))
                except OSError:
                    continue
            kept_with_mtime.sort(key=lambda item: item[0], reverse=True)
            for _, path in kept_with_mtime[
                _multimodal_pkg._MEDIA_URL_CACHE_MAX_FILES :
            ]:
                if path.stem in active_keys:
                    continue
                path.unlink(missing_ok=True)

    async def _prune_url_cache_locks(
        self,
        *,
        active_keys: set[str],
        present_keys: set[str],
    ) -> None:
        """回收不再活跃且已无缓存文件的 URL 锁，避免字典无限增长。

        Prune stale URL locks with no active task/file to avoid unbounded growth.
        """
        async with self._url_cache_locks_guard:
            stale_keys = [
                key
                for key, lock in self._url_cache_locks.items()
                if key not in active_keys
                and key not in present_keys
                and not lock.locked()
            ]
            for key in stale_keys:
                self._url_cache_locks.pop(key, None)

    async def _build_content_items(
        self, media_type: str, media_content: str | list[str], prompt: str
    ) -> list[dict[str, Any]]:
        """构建请求内容项。

        Args:
            media_type: 媒体类型
            media_content: 媒体内容（URL/data URL），或其列表
            prompt: 提示词

        Returns:
            包含文本和媒体的内容项列表
        """
        content_items: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

        media_item_key = f"{media_type}_url"
        contents = media_content if isinstance(media_content, list) else [media_content]
        for mc in contents:
            content_items.append({"type": media_item_key, media_item_key: {"url": mc}})

        return content_items

    async def analyze(
        self,
        media_url: str,
        media_type: str = "auto",
        prompt_extra: str = "",
    ) -> dict[str, str]:
        """分析媒体文件。

        始终调用视觉模型进行真实分析，不会因历史缓存而跳过。

        Args:
            media_url: 媒体文件 URL 或本地路径
            media_type: 媒体类型，"auto" 表示自动检测
            prompt_extra: 补充提示词

        Returns:
            包含描述和类型特定信息的字典
        """
        detected_type = detect_media_type(media_url, media_type)
        safe_url = redact_string(media_url)
        logger.info(f"[媒体分析] 开始分析 {detected_type}: {safe_url[:50]}...")
        logger.debug(
            "[媒体分析] media_type=%s detected=%s url_len=%s prompt_extra_len=%s",
            media_type,
            detected_type,
            len(media_url),
            len(prompt_extra),
        )

        cache_key = f"{detected_type}:{media_url[:100]}:{prompt_extra}"
        if cache_key in self._cache:
            logger.debug("[媒体分析] 命中缓存: key=%s", cache_key[:120])
            return self._cache[cache_key]

        try:
            media_content = await self._load_media_content(media_url, detected_type)
        except Exception as exc:
            logger.error(f"无法读取媒体文件: {exc}")
            return {
                "description": ERROR_MESSAGES["read"].get(
                    detected_type, ERROR_MESSAGES["read"]["default"]
                )
            }

        try:
            prompt = read_text_resource(self._prompt_path)
        except Exception:
            async with aiofiles.open(self._prompt_path, "r", encoding="utf-8") as f:
                prompt = await f.read()

        logger.debug(
            "[媒体分析] prompt_len=%s path=%s",
            len(prompt),
            self._prompt_path,
        )

        if prompt_extra:
            prompt += f"\n\n【补充指令】\n{prompt_extra}"

        content_items = await self._build_content_items(
            detected_type, media_content, prompt
        )

        try:
            result = await self._requester.request(
                model_config=self._vision_config,
                messages=[{"role": "user", "content": content_items}],
                max_tokens=self._vision_config.max_tokens,
                call_type=f"vision_{detected_type}",
            )
            content = extract_choices_content(result)
            if logger.isEnabledFor(logging.DEBUG):
                log_debug_json(logger, "[媒体分析] 原始响应内容", content)

            parsed = _parse_analysis_response(content)

            result_dict: dict[str, str] = {"description": parsed["description"]}
            field_name = MEDIA_TYPE_TO_FIELD.get(detected_type)
            if field_name:
                result_dict[field_name] = parsed[field_name]

            self._cache[cache_key] = result_dict
            logger.info(f"[媒体分析] 完成并缓存: {safe_url[:50]}... ({detected_type})")
            return result_dict

        except Exception as exc:
            logger.exception(f"媒体分析失败: {exc}")
            return {
                "description": ERROR_MESSAGES["analyze"].get(
                    detected_type, ERROR_MESSAGES["analyze"]["default"]
                )
            }

    # ── 媒体键级别的 Q&A 历史管理 ──

    def _load_history(self) -> None:
        """从磁盘加载历史 Q&A 缓存。"""
        if not HISTORY_FILE_PATH.exists():
            return
        try:
            with open(HISTORY_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._file_history = data
            logger.info(
                "[媒体分析] 从磁盘加载历史缓存: %d 个文件", len(self._file_history)
            )
        except Exception as exc:
            logger.warning("[媒体分析] 加载历史缓存失败: %s", exc)

    async def _save_history(self) -> None:
        """将历史缓存写入磁盘。"""
        from Undefined.utils import io

        try:
            await io.write_json(HISTORY_FILE_PATH, self._file_history, use_lock=True)
        except Exception as exc:
            logger.error("[媒体分析] 历史缓存写入磁盘失败: %s", exc)

    def get_history(self, media_key: str) -> list[dict[str, str]]:
        """获取指定媒体键的历史 Q&A 记录。

        Args:
            media_key: 媒体唯一键（可包含作用域和文件身份）

        Returns:
            Q&A 列表，每项包含 ``q`` 和 ``a`` 两个键
        """
        pairs = self._file_history.get(media_key)
        if not pairs:
            return []
        return list(pairs[-MAX_QA_HISTORY:])

    async def save_history(self, media_key: str, question: str, answer: str) -> None:
        """保存一条 Q&A 到指定媒体键的历史记录（上限 5 条）并持久化。

        Args:
            media_key: 媒体唯一键（可包含作用域和文件身份）
            question: 提问内容
            answer: 分析回答
        """
        pairs = self._file_history.setdefault(media_key, [])
        pairs.append({"q": question, "a": answer})
        if len(pairs) > MAX_QA_HISTORY:
            self._file_history[media_key] = pairs[-MAX_QA_HISTORY:]
        await self._save_history()

    async def describe_image(
        self, image_url: str, prompt_extra: str = ""
    ) -> dict[str, str]:
        """描述图片内容。

        Args:
            image_url: 图片 URL 或本地路径
            prompt_extra: 补充提示词

        Returns:
            包含描述和 OCR 文字的字典
        """
        result = await self.analyze(image_url, "image", prompt_extra)
        if "ocr_text" not in result:
            result["ocr_text"] = ""
        return result

    async def _load_prompt_text(self, prompt_path: str) -> str:
        try:
            return read_text_resource(prompt_path)
        except Exception:
            async with aiofiles.open(prompt_path, "r", encoding="utf-8") as f:
                return await f.read()

    def _build_tool_request_kwargs(self) -> dict[str, Any]:
        request_kwargs: dict[str, Any] = {}
        # 非 thinking 模型强制关闭 thinking，避免 tool_choice 被服务商拒绝
        if (
            get_api_mode(self._vision_config) == API_MODE_CHAT_COMPLETIONS
            and not self._vision_config.thinking_enabled
        ):
            request_kwargs["thinking"] = {"enabled": False, "budget_tokens": 0}
        return request_kwargs

    async def _request_required_tool_args(
        self,
        *,
        prompt_path: str,
        image_url: str | list[str],
        tool_schema: dict[str, Any],
        tool_name: str,
        call_type: str,
        max_tokens: int,
    ) -> dict[str, Any]:
        if isinstance(image_url, list):
            media_contents: list[str] = []
            for url in image_url:
                media_contents.append(await self._load_media_content(url, "image"))
            media_content: str | list[str] = media_contents
        else:
            media_content = await self._load_media_content(image_url, "image")
        prompt = await self._load_prompt_text(prompt_path)
        content_items = await self._build_content_items("image", media_content, prompt)
        response = await self._requester.request(
            model_config=self._vision_config,
            messages=[{"role": "user", "content": content_items}],
            max_tokens=max_tokens,
            call_type=call_type,
            tools=[tool_schema],
            tool_choice=cast(
                Any, {"type": "function", "function": {"name": tool_name}}
            ),
            **self._build_tool_request_kwargs(),
        )
        return extract_required_tool_call_arguments(
            response,
            expected_tool_name=tool_name,
            stage=call_type,
            logger=logger,
            error_context=f"image={redact_string(str(image_url) if isinstance(image_url, list) else image_url)[:120]}",
        )

    async def judge_meme_image(self, image_url: str | list[str]) -> dict[str, Any]:
        safe_url = redact_string(
            str(image_url) if isinstance(image_url, list) else image_url
        )
        try:
            args = await self._request_required_tool_args(
                prompt_path=MEME_JUDGE_PROMPT_PATH,
                image_url=image_url,
                tool_schema=MEME_JUDGE_TOOL,
                tool_name="submit_meme_judgement",
                call_type="vision_meme_judge",
                max_tokens=self._vision_config.max_tokens,
            )
        except Exception as exc:
            logger.exception("[媒体分析] 表情包判定失败，按非表情包处理: %s", exc)
            return {
                "is_meme": False,
                "confidence": 0.0,
                "reason": "",
            }

        try:
            parsed = {
                "is_meme": bool(args.get("is_meme", False)),
                "confidence": safe_float(args.get("confidence", 0.0), default=0.0),
                "reason": str(args.get("reason") or "").strip(),
            }
        except Exception:
            parsed = {"is_meme": False, "confidence": 0.0, "reason": ""}
        logger.info(
            "[媒体分析] 表情包判定完成: url=%s is_meme=%s confidence=%.3f reason=%s",
            safe_url[:50],
            parsed.get("is_meme", False),
            safe_float(parsed.get("confidence", 0.0), default=0.0),
            str(parsed.get("reason", ""))[:80],
        )
        return parsed

    async def describe_meme_image(self, image_url: str | list[str]) -> dict[str, Any]:
        safe_url = redact_string(
            str(image_url) if isinstance(image_url, list) else image_url
        )
        try:
            args = await self._request_required_tool_args(
                prompt_path=MEME_DESCRIBE_PROMPT_PATH,
                image_url=image_url,
                tool_schema=MEME_DESCRIBE_TOOL,
                tool_name="submit_meme_description",
                call_type="vision_meme_describe",
                max_tokens=self._vision_config.max_tokens,
            )
        except Exception as exc:
            logger.exception("[媒体分析] 表情包描述失败: %s", exc)
            return {"description": "", "tags": []}

        description = str(args.get("description") or "").strip()
        tags = _normalize_meme_tags(args.get("tags"))
        logger.info(
            "[媒体分析] 表情包描述完成: url=%s desc_len=%s tags=%s",
            safe_url[:50],
            len(description),
            tags,
        )
        return {"description": description, "tags": tags}


__all__ = ["MultimodalAnalyzer"]
