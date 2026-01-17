from pathlib import Path
from typing import Any, Dict
import base64
import logging
import aiofiles

logger = logging.getLogger(__name__)


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
    if media_type != "auto":
        return media_type

    suffix = path.suffix.lower()

    image_extensions = [
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".webp",
        ".svg",
        ".ico",
    ]
    audio_extensions = [".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".wma"]
    video_extensions = [".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"]

    if suffix in image_extensions:
        return "image"
    elif suffix in audio_extensions:
        return "audio"
    elif suffix in video_extensions:
        return "video"
    else:
        return "image"


def _get_mime_type(media_type: str, path: Path) -> str:
    mime_types = {
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

    suffix = path.suffix.lower()

    if media_type in mime_types and suffix in mime_types[media_type]:
        return mime_types[media_type][suffix]

    default_mimes = {
        "image": "image/jpeg",
        "audio": "audio/mpeg",
        "video": "video/mp4",
    }

    return default_mimes.get(media_type, "application/octet-stream")
