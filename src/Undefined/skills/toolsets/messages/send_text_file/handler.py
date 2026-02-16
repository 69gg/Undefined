from __future__ import annotations

import asyncio
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, Literal

logger = logging.getLogger(__name__)

TargetType = Literal["group", "private"]

MAX_FILENAME_LENGTH = 128
DEFAULT_MAX_FILE_SIZE_BYTES = 512 * 1024

ALLOWED_ENCODINGS: set[str] = {"utf-8", "utf-8-sig", "ascii", "gbk"}

ALLOWED_TEXT_EXTENSIONS: set[str] = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".vue",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".less",
    ".sass",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".cxx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".php",
    ".rb",
    ".swift",
    ".lua",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".bat",
    ".md",
    ".markdown",
    ".txt",
    ".rst",
    ".adoc",
    ".tex",
    ".latex",
    ".org",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".xml",
    ".csv",
    ".tsv",
    ".sql",
    ".log",
}

ALLOWED_SPECIAL_FILENAMES: set[str] = {
    "dockerfile",
    "makefile",
    "cmakelists.txt",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    ".npmrc",
    ".nvmrc",
    "requirements.txt",
}


def _parse_positive_int(value: Any, field_name: str) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, f"{field_name} 必须是整数"
    if parsed <= 0:
        return None, f"{field_name} 必须是正整数"
    return parsed, None


def _resolve_target(
    args: Dict[str, Any], context: Dict[str, Any]
) -> tuple[tuple[TargetType, int] | None, str | None]:
    target_type_raw = args.get("target_type")
    target_id_raw = args.get("target_id")
    has_target_type = target_type_raw is not None
    has_target_id = target_id_raw is not None

    if has_target_type or has_target_id:
        if not has_target_type and has_target_id:
            return None, "target_type 与 target_id 必须同时提供"

        if not isinstance(target_type_raw, str):
            return None, "target_type 必须是字符串（group 或 private）"

        target_type = target_type_raw.strip().lower()
        if target_type not in ("group", "private"):
            return None, "target_type 只能是 group 或 private"

        normalized_target_type: TargetType = (
            "group" if target_type == "group" else "private"
        )

        if has_target_id:
            target_id, target_id_error = _parse_positive_int(target_id_raw, "target_id")
            if target_id_error or target_id is None:
                return None, target_id_error or "target_id 非法"
            return (normalized_target_type, target_id), None

        request_type = context.get("request_type")
        if request_type != normalized_target_type:
            return None, "target_type 与当前会话类型不一致，无法推断 target_id"

        if normalized_target_type == "group":
            group_id, group_error = _parse_positive_int(
                context.get("group_id"), "group_id"
            )
            if group_error or group_id is None:
                return None, group_error or "无法根据 target_type 推断 target_id"
            return ("group", group_id), None

        user_id, user_error = _parse_positive_int(context.get("user_id"), "user_id")
        if user_error or user_id is None:
            return None, user_error or "无法根据 target_type 推断 target_id"
        return ("private", user_id), None

    request_type = context.get("request_type")
    if request_type == "group":
        group_id, group_error = _parse_positive_int(context.get("group_id"), "group_id")
        if group_error:
            return None, group_error
        if group_id is not None:
            return ("group", group_id), None
    elif request_type == "private":
        user_id, user_error = _parse_positive_int(context.get("user_id"), "user_id")
        if user_error:
            return None, user_error
        if user_id is not None:
            return ("private", user_id), None

    fallback_group_id, fallback_group_error = _parse_positive_int(
        context.get("group_id"), "group_id"
    )
    if fallback_group_error:
        return None, fallback_group_error
    if fallback_group_id is not None:
        return ("group", fallback_group_id), None

    fallback_user_id, fallback_user_error = _parse_positive_int(
        context.get("user_id"), "user_id"
    )
    if fallback_user_error:
        return None, fallback_user_error
    if fallback_user_id is not None:
        return ("private", fallback_user_id), None

    return None, "无法确定目标会话，请提供 target_type 与 target_id"


def _validate_filename(filename: str) -> str | None:
    if not filename:
        return "filename 不能为空"
    if len(filename) > MAX_FILENAME_LENGTH:
        return f"filename 过长，最多 {MAX_FILENAME_LENGTH} 个字符"
    if any(ch in filename for ch in ("/", "\\", "\x00")):
        return "filename 只能是单文件名，不能包含路径"
    if filename in {".", ".."}:
        return "filename 非法"
    if Path(filename).name != filename:
        return "filename 只能是单文件名，不能包含路径"

    lowered = filename.lower()
    if lowered in ALLOWED_SPECIAL_FILENAMES:
        return None

    suffix = Path(filename).suffix.lower()
    if suffix in ALLOWED_TEXT_EXTENSIONS:
        return None

    return (
        "不支持的文本文件格式。建议使用常见代码/文档/配置扩展名；"
        "多文件或复杂交付请使用 code_delivery_agent"
    )


def _resolve_onebot_client(context: Dict[str, Any]) -> Any | None:
    onebot_client = context.get("onebot_client")
    if onebot_client is not None:
        return onebot_client

    sender = context.get("sender")
    if sender is None:
        return None

    return getattr(sender, "onebot", None)


def _resolve_max_file_size_bytes(runtime_config: Any) -> int:
    if runtime_config is None:
        return DEFAULT_MAX_FILE_SIZE_BYTES

    raw_value = getattr(runtime_config, "messages_send_text_file_max_size_kb", 512)
    try:
        size_kb = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_FILE_SIZE_BYTES

    if size_kb <= 0:
        return DEFAULT_MAX_FILE_SIZE_BYTES
    return size_kb * 1024


async def _write_text_file(
    file_path: Path, content: str, encoding: str
) -> tuple[str, int]:
    def sync_write() -> tuple[str, int]:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding=encoding, newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        abs_path = str(file_path.resolve())
        file_size = file_path.stat().st_size
        return abs_path, file_size

    return await asyncio.to_thread(sync_write)


async def _cleanup_directory(path: Path) -> None:
    def sync_cleanup() -> None:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    await asyncio.to_thread(sync_cleanup)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """发送单文件文本内容到群聊或私聊。"""
    request_id = str(context.get("request_id", "-"))

    content_raw = args.get("content")
    if not isinstance(content_raw, str) or not content_raw:
        return "content 不能为空"
    content = content_raw

    filename = str(args.get("filename", "")).strip()
    filename_error = _validate_filename(filename)
    if filename_error:
        return filename_error

    encoding = str(args.get("encoding", "utf-8")).strip().lower() or "utf-8"
    if encoding not in ALLOWED_ENCODINGS:
        return "encoding 仅支持 utf-8 / utf-8-sig / ascii / gbk"

    runtime_config = context.get("runtime_config")
    max_file_size_bytes = _resolve_max_file_size_bytes(runtime_config)

    try:
        payload_size = len(content.encode(encoding))
    except UnicodeEncodeError:
        return f"编码 {encoding} 无法表示当前内容，请改用 utf-8"

    if payload_size > max_file_size_bytes:
        return (
            f"文件内容过大（{payload_size / 1024:.1f}KB），"
            f"当前限制 {max_file_size_bytes / 1024:.0f}KB。"
            "单文件请精简后重试；多文件或大体量交付建议使用 code_delivery_agent"
        )

    target, target_error = _resolve_target(args, context)
    if target_error or target is None:
        logger.warning(
            "[发送文本文件] 目标解析失败: request_id=%s err=%s",
            request_id,
            target_error,
        )
        return f"发送失败：{target_error or '目标参数错误'}"

    target_type, target_id = target

    if runtime_config is not None:
        if target_type == "group" and not runtime_config.is_group_allowed(target_id):
            return f"发送失败：目标群 {target_id} 不在允许列表内（access.allowed_group_ids）"
        if target_type == "private" and not runtime_config.is_private_allowed(
            target_id
        ):
            return f"发送失败：目标用户 {target_id} 不在允许列表内（access.allowed_private_ids）"

    onebot_client = _resolve_onebot_client(context)
    if onebot_client is None:
        return "发送失败：OneBot 客户端未设置"

    from Undefined.utils.paths import TEXT_FILE_CACHE_DIR, ensure_dir

    task_uuid = uuid.uuid4().hex
    task_dir = ensure_dir(TEXT_FILE_CACHE_DIR / task_uuid)
    file_path = task_dir / filename

    try:
        abs_path, file_size = await _write_text_file(file_path, content, encoding)
        if target_type == "group":
            await onebot_client.upload_group_file(target_id, abs_path, filename)
        else:
            await onebot_client.upload_private_file(target_id, abs_path, filename)

        context["message_sent_this_turn"] = True
        logger.info(
            "[发送文本文件] 成功: request_id=%s target_type=%s target_id=%s file=%s size=%sB",
            request_id,
            target_type,
            target_id,
            filename,
            file_size,
        )
        return (
            f"文件已发送：{filename} ({file_size / 1024:.1f}KB) -> "
            f"{target_type} {target_id}"
        )
    except UnicodeEncodeError:
        return f"编码 {encoding} 无法表示当前内容，请改用 utf-8"
    except Exception as exc:
        logger.exception(
            "[发送文本文件] 失败: request_id=%s target_type=%s target_id=%s file=%s err=%s",
            request_id,
            target_type,
            target_id,
            filename,
            exc,
        )
        return "发送失败：文件上传服务暂时不可用，请稍后重试"
    finally:
        try:
            await _cleanup_directory(task_dir)
        except Exception as cleanup_error:
            logger.warning(
                "[发送文本文件] 清理缓存失败: request_id=%s task_uuid=%s err=%s",
                request_id,
                task_uuid,
                cleanup_error,
            )
