from __future__ import annotations

import asyncio
import logging
import os
import shutil
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Dict, Literal, cast
from urllib.parse import unquote, urlparse

import aiofiles
import httpx

from Undefined.skills.http_client import request_with_retry
from Undefined.skills.http_config import get_request_timeout

logger = logging.getLogger(__name__)

TargetType = Literal["group", "private"]

MAX_FILENAME_LENGTH = 128
DEFAULT_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 64 * 1024


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


def _resolve_onebot_client(context: Dict[str, Any]) -> Any | None:
    onebot_client = context.get("onebot_client")
    if onebot_client is not None:
        return onebot_client

    sender = context.get("sender")
    if sender is None:
        return None

    return getattr(sender, "onebot", None)


def _resolve_file_send_callable(
    context: Dict[str, Any],
    target_type: TargetType,
) -> tuple[
    Callable[[int, str, str | None], Awaitable[Any]] | None,
    bool,
    str | None,
]:
    sender = context.get("sender")
    if sender is not None:
        sender_method_name = (
            "send_group_file" if target_type == "group" else "send_private_file"
        )
        sender_callable = getattr(sender, sender_method_name, None)
        if callable(sender_callable):
            return (
                cast(Callable[[int, str, str | None], Awaitable[Any]], sender_callable),
                True,
                None,
            )

    onebot_client = _resolve_onebot_client(context)
    if onebot_client is None:
        return None, False, "发送失败：统一发送层未设置"

    onebot_method_name = (
        "upload_group_file" if target_type == "group" else "upload_private_file"
    )
    onebot_callable = getattr(onebot_client, onebot_method_name, None)
    if not callable(onebot_callable):
        return None, False, "发送失败：统一发送层未设置"
    return (
        cast(Callable[[int, str, str | None], Awaitable[Any]], onebot_callable),
        False,
        None,
    )


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.2f}MB"
    return f"{size_bytes / 1024 / 1024 / 1024:.2f}GB"


async def _record_file_history_if_needed(
    context: Dict[str, Any],
    target_type: TargetType,
    target_id: int,
    file_name: str,
    file_size: int,
) -> None:
    history_manager = context.get("history_manager")
    if history_manager is None:
        return

    message = f"[文件] {file_name} ({_format_size(file_size)})"
    runtime_config = context.get("runtime_config")
    bot_qq_raw = getattr(runtime_config, "bot_qq", 0)
    try:
        bot_qq = int(bot_qq_raw)
    except (TypeError, ValueError):
        bot_qq = 0

    try:
        if target_type == "group":
            await history_manager.add_group_message(
                group_id=target_id,
                sender_id=bot_qq,
                text_content=message,
                sender_nickname="Bot",
                group_name="",
            )
        else:
            await history_manager.add_private_message(
                user_id=target_id,
                text_content=message,
                display_name="Bot",
                user_name="Bot",
            )
    except Exception:
        logger.exception(
            "[URL文件发送] 记录历史失败: target_type=%s target_id=%s file=%s",
            target_type,
            target_id,
            file_name,
        )


def _resolve_max_file_size_bytes(runtime_config: Any) -> int:
    if runtime_config is None:
        return DEFAULT_MAX_FILE_SIZE_BYTES

    raw_value = getattr(runtime_config, "messages_send_url_file_max_size_mb", 100)
    try:
        size_mb = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_FILE_SIZE_BYTES

    if size_mb <= 0:
        return DEFAULT_MAX_FILE_SIZE_BYTES
    return size_mb * 1024 * 1024


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
    return None


def _sanitize_filename(raw_name: str) -> str:
    name = raw_name.strip().strip("\"'")
    name = name.replace("\r", "").replace("\n", "")
    name = name.split("/")[-1].split("\\")[-1]
    return name.strip()


def _extract_filename_from_content_disposition(
    content_disposition: str | None,
) -> str | None:
    if not content_disposition:
        return None

    segments = [segment.strip() for segment in content_disposition.split(";")]

    for segment in segments:
        if not segment.lower().startswith("filename*="):
            continue
        value = segment.split("=", 1)[1].strip().strip('"')
        if "''" in value:
            value = value.split("''", 1)[1]
        decoded = unquote(value)
        filename = _sanitize_filename(decoded)
        if filename:
            return filename

    for segment in segments:
        if not segment.lower().startswith("filename="):
            continue
        value = segment.split("=", 1)[1]
        filename = _sanitize_filename(unquote(value))
        if filename:
            return filename

    return None


def _extract_filename_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    raw_name = Path(parsed.path).name
    if not raw_name:
        return None
    filename = _sanitize_filename(unquote(raw_name))
    return filename or None


def _resolve_filename(
    args: Dict[str, Any],
    head_headers: httpx.Headers,
    final_url: str,
    task_uuid: str,
) -> tuple[str | None, str | None]:
    filename_raw = args.get("filename")
    if filename_raw is not None:
        filename = str(filename_raw).strip()
        filename_error = _validate_filename(filename)
        if filename_error:
            return None, filename_error
        return filename, None

    inferred = _extract_filename_from_content_disposition(
        head_headers.get("content-disposition")
    )
    if not inferred:
        inferred = _extract_filename_from_url(final_url)
    if not inferred:
        inferred = f"url_file_{task_uuid[:8]}.bin"

    filename_error = _validate_filename(inferred)
    if filename_error:
        return None, f"自动推断文件名失败：{filename_error}"
    return inferred, None


def _resolve_content_length(
    content_length_raw: str | None,
) -> tuple[int | None, str | None]:
    if content_length_raw is None:
        return None, "无法获取文件大小（缺少 Content-Length）"

    try:
        content_length = int(content_length_raw)
    except (TypeError, ValueError):
        return None, "无法获取文件大小（Content-Length 非法）"

    if content_length <= 0:
        return None, "无法获取文件大小（Content-Length 非正数）"

    return content_length, None


async def _download_to_local_file(
    url: str,
    target_path: Path,
    expected_size: int,
    max_file_size_bytes: int,
    timeout_seconds: float,
) -> tuple[str, int]:
    part_path = target_path.with_suffix(f"{target_path.suffix}.part")

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        downloaded_size = 0

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()

                get_size_raw = response.headers.get("content-length")
                if get_size_raw is not None:
                    get_size, get_size_error = _resolve_content_length(get_size_raw)
                    if get_size_error or get_size is None:
                        raise ValueError(get_size_error or "下载响应大小非法")
                    if get_size != expected_size:
                        raise ValueError("文件大小与预检不一致，已取消发送")

                async with aiofiles.open(part_path, "wb") as f:
                    async for chunk in response.aiter_bytes(
                        chunk_size=DOWNLOAD_CHUNK_SIZE
                    ):
                        if not chunk:
                            continue
                        downloaded_size += len(chunk)
                        if downloaded_size > max_file_size_bytes:
                            raise ValueError("下载中发现文件超过大小限制，已取消发送")
                        if downloaded_size > expected_size:
                            raise ValueError("下载中发现文件超出预检大小，已取消发送")
                        await f.write(chunk)
                    await f.flush()

        if downloaded_size != expected_size:
            raise ValueError("下载完成后大小与预检不一致，已取消发送")

        await asyncio.to_thread(os.replace, part_path, target_path)
        abs_path = str(target_path.resolve())
        return abs_path, downloaded_size
    finally:
        if part_path.exists():
            try:
                part_path.unlink()
            except OSError:
                pass


async def _cleanup_directory(path: Path) -> None:
    def sync_cleanup() -> None:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    await asyncio.to_thread(sync_cleanup)


def _group_access_error(runtime_config: Any, group_id: int) -> str:
    reason_getter = getattr(runtime_config, "group_access_denied_reason", None)
    reason = reason_getter(group_id) if callable(reason_getter) else None
    if reason == "blacklist":
        return f"发送失败：目标群 {group_id} 在黑名单内（access.blocked_group_ids）"
    return f"发送失败：目标群 {group_id} 不在允许列表内（access.allowed_group_ids）"


def _private_access_error(runtime_config: Any, user_id: int) -> str:
    reason_getter = getattr(runtime_config, "private_access_denied_reason", None)
    reason = reason_getter(user_id) if callable(reason_getter) else None
    if reason == "blacklist":
        return f"发送失败：目标用户 {user_id} 在黑名单内（access.blocked_private_ids）"
    return f"发送失败：目标用户 {user_id} 不在允许列表内（access.allowed_private_ids）"


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """从 URL 下载文件并发送到群聊或私聊。"""
    request_id = str(context.get("request_id", "-"))

    url = str(args.get("url", "")).strip()
    if not url:
        return "url 不能为空"
    if not (url.startswith("http://") or url.startswith("https://")):
        return "url 仅支持 http/https"

    target, target_error = _resolve_target(args, context)
    if target_error or target is None:
        logger.warning(
            "[URL文件发送] 目标解析失败: request_id=%s err=%s",
            request_id,
            target_error,
        )
        return f"发送失败：{target_error or '目标参数错误'}"

    target_type, target_id = target

    runtime_config = context.get("runtime_config")
    if runtime_config is not None:
        if target_type == "group" and not runtime_config.is_group_allowed(target_id):
            return _group_access_error(runtime_config, target_id)
        if target_type == "private" and not runtime_config.is_private_allowed(
            target_id
        ):
            return _private_access_error(runtime_config, target_id)

    send_file_callable, history_recorded_by_sender, sender_error = (
        _resolve_file_send_callable(context, target_type)
    )
    if sender_error or send_file_callable is None:
        return sender_error or "发送失败：统一发送层未设置"

    max_file_size_bytes = _resolve_max_file_size_bytes(runtime_config)
    timeout_seconds = max(get_request_timeout(480.0), 15.0)
    head_timeout_seconds = min(timeout_seconds, 60.0)

    try:
        head_response = await request_with_retry(
            "HEAD",
            url,
            timeout=head_timeout_seconds,
            follow_redirects=True,
            context=context,
        )
    except Exception as exc:
        logger.warning(
            "[URL文件发送] 预检失败: request_id=%s url=%s err=%s",
            request_id,
            url,
            exc,
        )
        return "发送失败：无法获取文件大小，已取消发送"

    content_length, content_length_error = _resolve_content_length(
        head_response.headers.get("content-length")
    )
    if content_length_error or content_length is None:
        logger.warning(
            "[URL文件发送] 缺少大小信息: request_id=%s url=%s err=%s",
            request_id,
            url,
            content_length_error,
        )
        return "发送失败：无法获取文件大小，已取消发送"

    if content_length > max_file_size_bytes:
        return (
            f"发送失败：文件大小 {content_length / 1024 / 1024:.2f}MB 超过限制 "
            f"{max_file_size_bytes / 1024 / 1024:.0f}MB"
        )

    from Undefined.utils.paths import URL_FILE_CACHE_DIR, ensure_dir

    task_uuid = uuid.uuid4().hex
    task_dir = ensure_dir(URL_FILE_CACHE_DIR / task_uuid)

    final_url = str(head_response.url)
    filename, filename_error = _resolve_filename(
        args,
        head_response.headers,
        final_url,
        task_uuid,
    )
    if filename_error or filename is None:
        await _cleanup_directory(task_dir)
        return filename_error or "发送失败：文件名无效"

    file_path = task_dir / filename

    try:
        abs_path, downloaded_size = await _download_to_local_file(
            url=final_url,
            target_path=file_path,
            expected_size=content_length,
            max_file_size_bytes=max_file_size_bytes,
            timeout_seconds=timeout_seconds,
        )

        await send_file_callable(target_id, abs_path, filename)

        if not history_recorded_by_sender:
            await _record_file_history_if_needed(
                context=context,
                target_type=target_type,
                target_id=target_id,
                file_name=filename,
                file_size=downloaded_size,
            )

        context["message_sent_this_turn"] = True
        logger.info(
            "[URL文件发送] 成功: request_id=%s target_type=%s target_id=%s file=%s size=%sB url=%s",
            request_id,
            target_type,
            target_id,
            filename,
            downloaded_size,
            final_url,
        )
        return (
            f"文件已发送：{filename} ({downloaded_size / 1024 / 1024:.2f}MB) -> "
            f"{target_type} {target_id}"
        )
    except ValueError as exc:
        logger.warning(
            "[URL文件发送] 预检/下载校验失败: request_id=%s url=%s err=%s",
            request_id,
            final_url,
            exc,
        )
        return f"发送失败：{exc}"
    except Exception as exc:
        logger.exception(
            "[URL文件发送] 失败: request_id=%s target_type=%s target_id=%s url=%s err=%s",
            request_id,
            target_type,
            target_id,
            final_url,
            exc,
        )
        return "发送失败：文件上传服务暂时不可用，请稍后重试"
    finally:
        try:
            await _cleanup_directory(task_dir)
        except Exception as cleanup_error:
            logger.warning(
                "[URL文件发送] 清理缓存失败: request_id=%s task_uuid=%s err=%s",
                request_id,
                task_uuid,
                cleanup_error,
            )
