from pathlib import Path
from typing import Any, Dict
import base64
import logging
import aiofiles

logger = logging.getLogger(__name__)


# 媒体类型的 MIME 映射表
MIME_TYPES_MAP = {
    "image": {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
    },
    "audio": {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".wma": "audio/x-ms-wma",
    },
    "video": {
        ".mp4": "video/mp4",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
        ".flv": "video/x-flv",
        ".wmv": "video/x-ms-wmv",
    },
}

# 默认 MIME 类型
DEFAULT_MIMES = {
    "image": "image/jpeg",
    "audio": "audio/mpeg",
    "video": "video/mp4",
}

# 扩展名分组
EXTENSION_GROUPS = {
    "image": [
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".webp",
        ".svg",
        ".ico",
    ],
    "audio": [".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".wma"],
    "video": [".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"],
}


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    file_path: str = args.get("file_path", "")
    media_type: str = args.get("media_type", "auto")
    prompt_extra: str = args.get("prompt", "")

    path = Path(file_path)

    if not path.exists():
        return f"错误：文件不存在 {file_path}"

    if not path.is_file():
        return f"错误：{file_path} 不是文件"

    ai_client = context.get("ai_client")
    if not ai_client:
        return "错误：AI client 未在上下文中提供"

    try:
        detected_type = _detect_media_type(path, media_type)

        with open(path, "rb") as f:
            media_data = base64.b64encode(f.read()).decode()

        mime_type = _get_mime_type(detected_type, path)
        media_content = f"data:{mime_type};base64,{media_data}"

        async with aiofiles.open(
            "res/prompts/analyze_multimodal.txt", "r", encoding="utf-8"
        ) as f:
            prompt = await f.read()

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

        response = await ai_client._http_client.post(
            ai_client.vision_config.api_url,
            headers={
                "Authorization": f"Bearer {ai_client.vision_config.api_key}",
                "Content-Type": "application/json",
            },
            json=ai_client._build_request_body(
                model_config=ai_client.vision_config,
                messages=[{"role": "user", "content": content_items}],
                max_tokens=8192,
            ),
        )
        response.raise_for_status()
        result = response.json()

        content = ai_client._extract_choices_content(result)
        return str(content) if content else "分析失败"

    except Exception as e:
        logger.exception(f"多模态分析失败: {e}")
        return f"多模态分析失败: {e}"


def _detect_media_type(path: Path, media_type: str) -> str:
    """根据文件扩展名检测媒体类型

    参数:
        path: 文件路径
        media_type: 用户指定的媒体类型（如果是 "auto" 则自动检测）

    返回:
        检测到的媒体类型 ("image", "audio", "video" 或默认 "image")
    """
    if media_type != "auto":
        return media_type

    suffix = path.suffix.lower()

    if suffix in EXTENSION_GROUPS["image"]:
        return "image"
    elif suffix in EXTENSION_GROUPS["audio"]:
        return "audio"
    elif suffix in EXTENSION_GROUPS["video"]:
        return "video"
    else:
        return "image"


def _get_mime_type(media_type: str, path: Path) -> str:
    """获取文件的 MIME 类型

    参数:
        media_type: 媒体类型
        path: 文件路径

    返回:
        MIME 类型字符串
    """
    suffix = path.suffix.lower()

    if media_type in MIME_TYPES_MAP and suffix in MIME_TYPES_MAP[media_type]:
        return MIME_TYPES_MAP[media_type][suffix]

    return DEFAULT_MIMES.get(media_type, "application/octet-stream")
