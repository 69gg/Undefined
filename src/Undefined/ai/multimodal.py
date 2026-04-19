"""多模态分析辅助函数。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any, cast
from urllib.parse import urlsplit

import aiofiles
import httpx

from Undefined.ai.parsing import extract_choices_content
from Undefined.utils.coerce import safe_float
from Undefined.ai.llm import ModelRequester
from Undefined.config import VisionModelConfig
from Undefined.ai.transports import API_MODE_CHAT_COMPLETIONS, get_api_mode
from Undefined.utils.tool_calls import extract_required_tool_call_arguments
from Undefined.utils.logging import log_debug_json, redact_string
from Undefined.utils.resources import read_text_resource

logger = logging.getLogger(__name__)

# 每个文件名最多保留的历史 Q&A 条数
_MAX_QA_HISTORY = 5

# 磁盘持久化路径
_HISTORY_FILE_PATH = Path("data/media_qa_history.json")

# 远程媒体缓存目录（用于先下载 URL 再转 data URL）
# Remote media cache directory (download URL first, then convert to data URL).
_MEDIA_URL_CACHE_DIR = Path("data/cache/multimodal_media")

# 远程媒体缓存清理策略：仅保留最近 6 小时 + 最多 256 个文件。
# Remote media cache cleanup policy: keep only recent 6h + max 256 files.
_MEDIA_URL_CACHE_TTL_SECONDS = 6 * 60 * 60
_MEDIA_URL_CACHE_MAX_FILES = 256

# 两次自动清理之间的最小间隔（秒），避免每次请求都全量扫描目录。
# Minimum interval between cleanup runs (seconds) to avoid full scan on every call.
_MEDIA_URL_CACHE_CLEANUP_INTERVAL_SECONDS = 60.0

# 下载 URL 到本地缓存时的网络超时（秒）。
# Network timeout (seconds) when downloading URL to local cache.
_MEDIA_URL_DOWNLOAD_TIMEOUT_SECONDS = 120.0

# 下载阶段临时文件后缀（追加在缓存文件名后），用于区分真实缓存文件。
# Download-stage temporary suffix (appended to cache filename) to avoid clashes.
_MEDIA_URL_DOWNLOAD_TMP_SUFFIX = ".downloading"

# 文件扩展名常量
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")
_AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma")
_VIDEO_EXTENSIONS = (".mp4", ".avi", ".mov", ".webm", ".mkv", ".flv", ".wmv")

# MIME 类型前缀到媒体类型的映射
_MIME_PREFIX_TO_TYPE = {
    "image/": "image",
    "audio/": "audio",
    "video/": "video",
}


def _extract_mime_type_from_data_url(media_url: str) -> str | None:
    """从 data URL 中提取 MIME 类型。

    Args:
        media_url: 媒体 URL

    Returns:
        MIME 类型前缀（如 "image/"）或 None
    """
    if not media_url.startswith("data:"):
        return None
    mime_part = media_url.split(";")[0]
    if ":" in mime_part:
        return mime_part.split(":")[1]
    return None


def _get_media_type_by_extension(url_lower: str) -> str:
    """根据文件扩展名判断媒体类型。

    Args:
        url_lower: 转换为小写的 URL

    Returns:
        媒体类型（"image"、"audio" 或 "video"）
    """
    for ext in _IMAGE_EXTENSIONS:
        if ext in url_lower:
            return "image"
    for ext in _AUDIO_EXTENSIONS:
        if ext in url_lower:
            return "audio"
    for ext in _VIDEO_EXTENSIONS:
        if ext in url_lower:
            return "video"
    return "image"  # 默认返回图片类型


def detect_media_type(media_url: str, specified_type: str = "auto") -> str:
    """检测媒体文件的类型（图片、音频或视频）。"""
    # 1. 优先级最高：手动指定类型
    if specified_type and specified_type != "auto":
        return specified_type

    # 2. 检查 data URL
    media_type = _detect_from_data_url(media_url)
    if media_type:
        return media_type

    # 3. 使用 mimetypes 或扩展名猜测
    return _detect_by_mimetypes(media_url)


def _detect_from_data_url(media_url: str) -> str | None:
    """从 data URL 的 MIME 类型中探测媒体类型"""
    mime = _extract_mime_type_from_data_url(media_url)
    if mime:
        for prefix, media_type in _MIME_PREFIX_TO_TYPE.items():
            if mime.startswith(prefix):
                return media_type
    return None


def _detect_by_mimetypes(media_url: str) -> str:
    """利用 mimetypes 库或扩展名探测媒体类型"""
    import mimetypes

    guessed_mime, _ = mimetypes.guess_type(media_url)
    if guessed_mime:
        for prefix, media_type in _MIME_PREFIX_TO_TYPE.items():
            if guessed_mime.startswith(prefix):
                return media_type

    return _get_media_type_by_extension(media_url.lower())


# 默认 MIME 类型映射
_DEFAULT_MIME_TYPES = {
    "image": "image/jpeg",
    "audio": "audio/mpeg",
    "video": "video/mp4",
}


def get_media_mime_type(media_type: str, file_path: str = "") -> str:
    """获取媒体文件的 MIME 类型。

    Args:
        media_type: 媒体类型（"image"、"audio" 或 "video"）
        file_path: 文件路径（可选），用于根据文件扩展名推断 MIME 类型

    Returns:
        MIME 类型字符串
    """
    # 如果提供了文件路径，优先使用 mimetypes 推断
    if file_path:
        import mimetypes

        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type:
            return mime_type

    # 返回默认 MIME 类型
    return _DEFAULT_MIME_TYPES.get(media_type, "application/octet-stream")


# 响应内容类型到字段名的映射
_MEDIA_TYPE_TO_FIELD = {
    "image": "ocr_text",
    "audio": "transcript",
    "video": "subtitles",
}

_MEME_JUDGE_PROMPT_PATH = "res/prompts/judge_meme_image.txt"
_MEME_DESCRIBE_PROMPT_PATH = "res/prompts/describe_meme_image.txt"

_MEME_JUDGE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_meme_judgement",
        "description": "提交表情包判定结果",
        "parameters": {
            "type": "object",
            "properties": {
                "is_meme": {
                    "type": "boolean",
                    "description": "该图片是否适合进入表情包库",
                },
                "confidence": {
                    "type": "number",
                    "description": "0 到 1 的置信度",
                },
                "reason": {
                    "type": "string",
                    "description": "简短中文判定原因",
                },
            },
            "required": ["is_meme", "confidence", "reason"],
        },
    },
}

_MEME_DESCRIBE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_meme_description",
        "description": "提交表情包描述与标签",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "适合检索的简短中文描述",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "0 到 6 个短标签",
                },
            },
            "required": ["description", "tags"],
        },
    },
}


# 错误消息映射
_ERROR_MESSAGES = {
    "read": {
        "image": "[图片无法读取]",
        "audio": "[音频无法读取]",
        "video": "[视频无法读取]",
        "default": "[媒体文件无法读取]",
    },
    "analyze": {
        "image": "[图片分析失败]",
        "audio": "[音频分析失败]",
        "video": "[视频分析失败]",
        "default": "[媒体分析失败]",
    },
}


def _parse_line_value(line: str, prefix: str) -> str:
    """解析行内容，提取指定前缀后的值。

    Args:
        line: 待解析的行
        prefix: 前缀（支持中文冒号和英文冒号）

    Returns:
        提取的值，如果值为 "无" 则返回空字符串
    """
    value = line.split("：", 1)[-1].split(":", 1)[-1].strip()
    return "" if value == "无" else value


def _parse_analysis_response(content: str) -> dict[str, str]:
    """解析 AI 分析响应的内容。

    Args:
        content: AI 返回的文本内容

    Returns:
        包含描述和类型特定字段的字典
    """
    # 字段前缀映射（支持中文冒号和英文冒号）
    field_prefixes = {
        "description": ("描述：", "描述:"),
        "ocr_text": ("OCR：", "OCR:"),
        "transcript": ("转写：", "转写:"),
        "subtitles": ("字幕：", "字幕:"),
    }

    # 初始化所有字段为空
    result = {
        "description": "",
        "ocr_text": "",
        "transcript": "",
        "subtitles": "",
    }

    # 解析每一行
    for line in content.split("\n"):
        line = line.strip()
        for field, prefixes in field_prefixes.items():
            if line.startswith(prefixes):
                result[field] = _parse_line_value(line, prefixes[0])

    # 如果没有解析到描述，使用完整内容作为描述
    if not result["description"]:
        result["description"] = content

    return result


def _extract_json_object(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {}
    candidates = [text]
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            stripped = part.strip()
            if not stripped:
                continue
            if stripped.lower().startswith("json"):
                stripped = stripped[4:].strip()
            candidates.append(stripped)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _normalize_meme_tags(tags_raw: Any) -> list[str]:
    tags: list[str] = []
    if isinstance(tags_raw, list):
        seen: set[str] = set()
        for item in tags_raw:
            text = str(item or "").strip()
            lowered = text.lower()
            if not text or lowered in seen:
                continue
            seen.add(lowered)
            tags.append(text)
    return tags


def _parse_meme_analysis_response(content: str) -> dict[str, Any]:
    parsed = _extract_json_object(content)
    return {
        "is_meme": bool(parsed.get("is_meme", False)),
        "confidence": safe_float(parsed.get("confidence", 0.0), default=0.0),
        "description": str(parsed.get("description") or "").strip(),
        "tags": _normalize_meme_tags(parsed.get("tags")),
    }


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
        return _MEDIA_URL_CACHE_DIR / f"{cache_key}{suffix}"

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
            f"{cache_path.name}{_MEDIA_URL_DOWNLOAD_TMP_SUFFIX}"
        )
        try:
            timeout = httpx.Timeout(_MEDIA_URL_DOWNLOAD_TIMEOUT_SECONDS)
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
        return len(suffixes) >= 2 and suffixes[-1] == _MEDIA_URL_DOWNLOAD_TMP_SUFFIX

    async def _cleanup_url_cache_if_needed(self) -> None:
        """按 TTL + 文件数上限清理 URL 媒体缓存。"""
        now = time.time()
        if (
            now - self._last_url_cache_cleanup_at
            < _MEDIA_URL_CACHE_CLEANUP_INTERVAL_SECONDS
        ):
            return

        async with self._url_cache_cleanup_lock:
            # 双重检查，避免并发情况下重复清理。
            # Double-check to avoid repeated cleanup under concurrency.
            now = time.time()
            if (
                now - self._last_url_cache_cleanup_at
                < _MEDIA_URL_CACHE_CLEANUP_INTERVAL_SECONDS
            ):
                return
            self._last_url_cache_cleanup_at = now

            async with self._url_cache_locks_guard:
                active_keys = {
                    key for key, lock in self._url_cache_locks.items() if lock.locked()
                }
            cache_dir = _MEDIA_URL_CACHE_DIR
            if not cache_dir.exists():
                await self._prune_url_cache_locks(
                    active_keys=active_keys,
                    present_keys=set(),
                )
                return

            files: list[Path] = [p for p in cache_dir.iterdir() if p.is_file()]
            expire_before = now - _MEDIA_URL_CACHE_TTL_SECONDS
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
            if len(kept_files) <= _MEDIA_URL_CACHE_MAX_FILES:
                return

            kept_with_mtime: list[tuple[float, Path]] = []
            for path in kept_files:
                try:
                    kept_with_mtime.append((path.stat().st_mtime, path))
                except OSError:
                    continue
            kept_with_mtime.sort(key=lambda item: item[0], reverse=True)
            for _, path in kept_with_mtime[_MEDIA_URL_CACHE_MAX_FILES:]:
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

        # 添加媒体内容项
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

        # 检查缓存
        cache_key = f"{detected_type}:{media_url[:100]}:{prompt_extra}"
        if cache_key in self._cache:
            logger.debug("[媒体分析] 命中缓存: key=%s", cache_key[:120])
            return self._cache[cache_key]

        # 加载媒体内容
        try:
            media_content = await self._load_media_content(media_url, detected_type)
        except Exception as exc:
            logger.error(f"无法读取媒体文件: {exc}")
            return {
                "description": _ERROR_MESSAGES["read"].get(
                    detected_type, _ERROR_MESSAGES["read"]["default"]
                )
            }

        # 加载提示词
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

        # 添加补充提示词
        if prompt_extra:
            prompt += f"\n\n【补充指令】\n{prompt_extra}"

        # 构建请求内容
        content_items = await self._build_content_items(
            detected_type, media_content, prompt
        )

        # 发送分析请求
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

            # 解析响应内容
            parsed = _parse_analysis_response(content)

            # 根据媒体类型构建结果字典
            result_dict: dict[str, str] = {"description": parsed["description"]}
            field_name = _MEDIA_TYPE_TO_FIELD.get(detected_type)
            if field_name:
                result_dict[field_name] = parsed[field_name]

            # 缓存结果
            self._cache[cache_key] = result_dict
            logger.info(f"[媒体分析] 完成并缓存: {safe_url[:50]}... ({detected_type})")
            return result_dict

        except Exception as exc:
            logger.exception(f"媒体分析失败: {exc}")
            return {
                "description": _ERROR_MESSAGES["analyze"].get(
                    detected_type, _ERROR_MESSAGES["analyze"]["default"]
                )
            }

    # ── 媒体键级别的 Q&A 历史管理 ──

    def _load_history(self) -> None:
        """从磁盘加载历史 Q&A 缓存。"""
        if not _HISTORY_FILE_PATH.exists():
            return
        try:
            with open(_HISTORY_FILE_PATH, "r", encoding="utf-8") as f:
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
            await io.write_json(_HISTORY_FILE_PATH, self._file_history, use_lock=True)
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
        return list(pairs[-_MAX_QA_HISTORY:])

    async def save_history(self, media_key: str, question: str, answer: str) -> None:
        """保存一条 Q&A 到指定媒体键的历史记录（上限 5 条）并持久化。

        Args:
            media_key: 媒体唯一键（可包含作用域和文件身份）
            question: 提问内容
            answer: 分析回答
        """
        pairs = self._file_history.setdefault(media_key, [])
        pairs.append({"q": question, "a": answer})
        if len(pairs) > _MAX_QA_HISTORY:
            self._file_history[media_key] = pairs[-_MAX_QA_HISTORY:]
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
                prompt_path=_MEME_JUDGE_PROMPT_PATH,
                image_url=image_url,
                tool_schema=_MEME_JUDGE_TOOL,
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
                prompt_path=_MEME_DESCRIBE_PROMPT_PATH,
                image_url=image_url,
                tool_schema=_MEME_DESCRIBE_TOOL,
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
