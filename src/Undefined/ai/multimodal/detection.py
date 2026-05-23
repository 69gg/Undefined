"""媒体类型探测与 MIME 推断。"""

from __future__ import annotations

from Undefined.ai.multimodal.constants import (
    AUDIO_EXTENSIONS,
    DEFAULT_MIME_TYPES,
    IMAGE_EXTENSIONS,
    MIME_PREFIX_TO_TYPE,
    VIDEO_EXTENSIONS,
)


def _extract_mime_type_from_data_url(media_url: str) -> str | None:
    """从 data URL 中提取 MIME 类型。

    Args:
        media_url: 媒体 URL

    Returns:
        MIME 类型前缀（如 ``image/``）或 None
    """
    if not media_url.startswith("data:"):
        return None
    mime_part = media_url.split(";")[0]
    if ":" in mime_part:
        return mime_part.split(":")[1]
    return None


def _get_media_type_by_extension(url_lower: str) -> str:
    """根据文件扩展名判断媒体类型。"""
    for ext in IMAGE_EXTENSIONS:
        if ext in url_lower:
            return "image"
    for ext in AUDIO_EXTENSIONS:
        if ext in url_lower:
            return "audio"
    for ext in VIDEO_EXTENSIONS:
        if ext in url_lower:
            return "video"
    return "image"


def detect_media_type(media_url: str, specified_type: str = "auto") -> str:
    """检测媒体文件的类型（图片、音频或视频）。"""
    if specified_type and specified_type != "auto":
        return specified_type

    # data URL 的 MIME 优先于扩展名猜测
    media_type = _detect_from_data_url(media_url)
    if media_type:
        return media_type

    return _detect_by_mimetypes(media_url)


def _detect_from_data_url(media_url: str) -> str | None:
    """从 data URL 的 MIME 类型中探测媒体类型。"""
    mime = _extract_mime_type_from_data_url(media_url)
    if mime:
        for prefix, media_type in MIME_PREFIX_TO_TYPE.items():
            if mime.startswith(prefix):
                return media_type
    return None


def _detect_by_mimetypes(media_url: str) -> str:
    """利用 mimetypes 库或扩展名探测媒体类型。"""
    import mimetypes

    guessed_mime, _ = mimetypes.guess_type(media_url)
    if guessed_mime:
        for prefix, media_type in MIME_PREFIX_TO_TYPE.items():
            if guessed_mime.startswith(prefix):
                return media_type

    return _get_media_type_by_extension(media_url.lower())


def get_media_mime_type(media_type: str, file_path: str = "") -> str:
    """获取媒体文件的 MIME 类型。

    Args:
        media_type: 媒体类型（``image``、``audio`` 或 ``video``）
        file_path: 文件路径（可选），用于根据扩展名推断 MIME 类型

    Returns:
        MIME 类型字符串
    """
    if file_path:
        import mimetypes

        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type:
            return mime_type

    return DEFAULT_MIME_TYPES.get(media_type, "application/octet-stream")


__all__ = ["detect_media_type", "get_media_mime_type"]
