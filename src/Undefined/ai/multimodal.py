"""Multimodal analysis helpers."""

from __future__ import annotations

import base64
import logging
from typing import Any

import aiofiles

from Undefined.ai.parsing import extract_choices_content
from Undefined.ai.http import ModelRequester
from Undefined.config import VisionModelConfig
from Undefined.utils.logging import log_debug_json, redact_string

logger = logging.getLogger(__name__)


def detect_media_type(media_url: str, specified_type: str = "auto") -> str:
    if specified_type and specified_type != "auto":
        return specified_type

    if media_url.startswith("data:"):
        data_mime_type = media_url.split(";")[0].split(":")[1]
        if data_mime_type.startswith("image/"):
            return "image"
        if data_mime_type.startswith("audio/"):
            return "audio"
        if data_mime_type.startswith("video/"):
            return "video"

    import mimetypes

    guessed_mime_type, _ = mimetypes.guess_type(media_url)
    if guessed_mime_type:
        if guessed_mime_type.startswith("image/"):
            return "image"
        if guessed_mime_type.startswith("audio/"):
            return "audio"
        if guessed_mime_type.startswith("video/"):
            return "video"

    url_lower = media_url.lower()
    image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"]
    audio_extensions = [".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma"]
    video_extensions = [".mp4", ".avi", ".mov", ".webm", ".mkv", ".flv", ".wmv"]

    for ext in image_extensions:
        if ext in url_lower:
            return "image"
    for ext in audio_extensions:
        if ext in url_lower:
            return "audio"
    for ext in video_extensions:
        if ext in url_lower:
            return "video"

    return "image"


def get_media_mime_type(media_type: str, file_path: str = "") -> str:
    if file_path:
        import mimetypes

        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type:
            return mime_type

    if media_type == "image":
        return "image/jpeg"
    if media_type == "audio":
        return "audio/mpeg"
    if media_type == "video":
        return "video/mp4"
    return "application/octet-stream"


class MultimodalAnalyzer:
    def __init__(
        self,
        requester: ModelRequester,
        vision_config: VisionModelConfig,
        prompt_path: str = "res/prompts/analyze_multimodal.txt",
    ) -> None:
        self._requester = requester
        self._vision_config = vision_config
        self._prompt_path = prompt_path
        self._cache: dict[str, dict[str, str]] = {}

    async def analyze(
        self,
        media_url: str,
        media_type: str = "auto",
        prompt_extra: str = "",
    ) -> dict[str, str]:
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

        if media_url.startswith("data:") or media_url.startswith("http"):
            media_content = media_url
        else:
            try:
                async with aiofiles.open(media_url, "rb") as f:
                    media_data = base64.b64encode(await f.read()).decode()
                mime_type = get_media_mime_type(detected_type, media_url)
                media_content = f"data:{mime_type};base64,{media_data}"
            except Exception as exc:
                logger.error(f"无法读取媒体文件: {exc}")
                error_msg = {
                    "image": "[图片无法读取]",
                    "audio": "[音频无法读取]",
                    "video": "[视频无法读取]",
                }.get(detected_type, "[媒体文件无法读取]")
                return {"description": error_msg}

        async with aiofiles.open(self._prompt_path, "r", encoding="utf-8") as f:
            prompt = await f.read()
        logger.debug(
            "[媒体分析] prompt_len=%s path=%s",
            len(prompt),
            self._prompt_path,
        )

        if prompt_extra:
            prompt += f"\n\n【补充指令】\n{prompt_extra}"

        content_items: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

        if detected_type == "image":
            content_items.append(
                {"type": "image_url", "image_url": {"url": media_content}}
            )
        elif detected_type == "audio":
            content_items.append(
                {"type": "audio_url", "audio_url": {"url": media_content}}
            )
        elif detected_type == "video":
            content_items.append(
                {"type": "video_url", "video_url": {"url": media_content}}
            )

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

            description = ""
            ocr_text = ""
            transcript = ""
            subtitles = ""

            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("描述：") or line.startswith("描述:"):
                    description = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                elif line.startswith("OCR：") or line.startswith("OCR:"):
                    ocr_text = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                    if ocr_text == "无":
                        ocr_text = ""
                elif line.startswith("转写：") or line.startswith("转写:"):
                    transcript = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                    if transcript == "无":
                        transcript = ""
                elif line.startswith("字幕：") or line.startswith("字幕:"):
                    subtitles = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                    if subtitles == "无":
                        subtitles = ""

            result_dict: dict[str, str] = {"description": description or content}
            if detected_type == "image":
                result_dict["ocr_text"] = ocr_text
            elif detected_type == "audio":
                result_dict["transcript"] = transcript
            elif detected_type == "video":
                result_dict["subtitles"] = subtitles

            self._cache[cache_key] = result_dict
            logger.info(f"[媒体分析] 完成并缓存: {safe_url[:50]}... ({detected_type})")
            return result_dict

        except Exception as exc:
            logger.exception(f"媒体分析失败: {exc}")
            error_msg = {
                "image": "[图片分析失败]",
                "audio": "[音频分析失败]",
                "video": "[视频分析失败]",
            }.get(detected_type, "[媒体分析失败]")
            return {"description": error_msg}

    async def describe_image(
        self, image_url: str, prompt_extra: str = ""
    ) -> dict[str, str]:
        result = await self.analyze(image_url, "image", prompt_extra)
        if "ocr_text" not in result:
            result["ocr_text"] = ""
        return result
