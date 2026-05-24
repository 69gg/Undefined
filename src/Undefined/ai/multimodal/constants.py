"""多模态分析常量与工具 schema 定义。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# ===== 历史 Q&A 与磁盘缓存 =====
# 每个文件名最多保留的历史 Q&A 条数
_MAX_QA_HISTORY = 5

HISTORY_FILE_PATH = Path("data/media_qa_history.json")

# ===== 远程 URL 媒体缓存策略 =====
# 远程媒体缓存目录（用于先下载 URL 再转 data URL）
_MEDIA_URL_CACHE_DIR = Path("data/cache/multimodal_media")

# 远程媒体缓存清理策略：仅保留最近 6 小时 + 最多 256 个文件。
_MEDIA_URL_CACHE_TTL_SECONDS = 6 * 60 * 60
_MEDIA_URL_CACHE_MAX_FILES = 256

# 两次自动清理之间的最小间隔（秒），避免每次请求都全量扫描目录。
_MEDIA_URL_CACHE_CLEANUP_INTERVAL_SECONDS = 60.0

# 下载 URL 到本地缓存时的网络超时（秒）。
_MEDIA_URL_DOWNLOAD_TIMEOUT_SECONDS = 120.0

# 下载阶段临时文件后缀（追加在缓存文件名后），用于区分真实缓存文件。
_MEDIA_URL_DOWNLOAD_TMP_SUFFIX = ".downloading"

# ===== 扩展名 / MIME / 错误文案映射 =====
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")
AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma")
VIDEO_EXTENSIONS = (".mp4", ".avi", ".mov", ".webm", ".mkv", ".flv", ".wmv")

# MIME 类型前缀到媒体类型的映射
MIME_PREFIX_TO_TYPE = {
    "image/": "image",
    "audio/": "audio",
    "video/": "video",
}

# 默认 MIME 类型映射
DEFAULT_MIME_TYPES = {
    "image": "image/jpeg",
    "audio": "audio/mpeg",
    "video": "video/mp4",
}

MEDIA_TYPE_TO_FIELD = {
    "image": "ocr_text",
    "audio": "transcript",
    "video": "subtitles",
}

# ===== 表情包判定 / 描述工具 schema =====
MEME_JUDGE_PROMPT_PATH = "res/prompts/judge_meme_image.txt"
MEME_DESCRIBE_PROMPT_PATH = "res/prompts/describe_meme_image.txt"

MEME_JUDGE_TOOL: dict[str, Any] = {
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

MEME_DESCRIBE_TOOL: dict[str, Any] = {
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

ERROR_MESSAGES = {
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

__all__ = [
    "DEFAULT_MIME_TYPES",
    "ERROR_MESSAGES",
    "HISTORY_FILE_PATH",
    "MAX_QA_HISTORY",
    "MEDIA_TYPE_TO_FIELD",
    "MEME_DESCRIBE_PROMPT_PATH",
    "MEME_DESCRIBE_TOOL",
    "MEME_JUDGE_PROMPT_PATH",
    "MEME_JUDGE_TOOL",
    "MIME_PREFIX_TO_TYPE",
]

# 对外别名，供 analyzer 使用
MAX_QA_HISTORY = _MAX_QA_HISTORY
