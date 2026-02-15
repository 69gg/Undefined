"""多模态分析辅助函数。"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any
import aiofiles

from Undefined.ai.parsing import extract_choices_content
from Undefined.ai.llm import ModelRequester
from Undefined.config import VisionModelConfig
from Undefined.utils.logging import log_debug_json, redact_string
from Undefined.utils.resources import read_text_resource

logger = logging.getLogger(__name__)

# 每个文件名最多保留的历史 Q&A 条数
_MAX_QA_HISTORY = 5

# 磁盘持久化路径
_HISTORY_FILE_PATH = Path("data/media_qa_history.json")

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
        if media_url.startswith("data:") or media_url.startswith("http"):
            return media_url

        # 读取本地文件并转换为 base64
        async with aiofiles.open(media_url, "rb") as f:
            media_data = base64.b64encode(await f.read()).decode()
        mime_type = get_media_mime_type(media_type, media_url)
        return f"data:{mime_type};base64,{media_data}"

    async def _build_content_items(
        self, media_type: str, media_content: str, prompt: str
    ) -> list[dict[str, Any]]:
        """构建请求内容项。

        Args:
            media_type: 媒体类型
            media_content: 媒体内容（URL 或 data URL）
            prompt: 提示词

        Returns:
            包含文本和媒体的内容项列表
        """
        content_items: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

        # 添加媒体内容项
        media_item_key = f"{media_type}_url"
        content_items.append(
            {"type": media_item_key, media_item_key: {"url": media_content}}
        )

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
                max_tokens=8192,
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
