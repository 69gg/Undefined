import uuid
import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, cast
import logging
import httpx
import aiofiles

logger = logging.getLogger(__name__)

SIZE_LIMITS = {
    "text": 10 * 1024 * 1024,
    "code": 5 * 1024 * 1024,
    "pdf": 50 * 1024 * 1024,
    "docx": 20 * 1024 * 1024,
    "pptx": 20 * 1024 * 1024,
    "xlsx": 10 * 1024 * 1024,
    "image": 10 * 1024 * 1024,
    "audio": 50 * 1024 * 1024,
    "video": 100 * 1024 * 1024,
    "archive": 100 * 1024 * 1024,
}

DEFAULT_SIZE_LIMIT = 100 * 1024 * 1024
_MAX_PATH_SOURCE_LENGTH = 4096


def _safe_download_filename(
    *,
    preferred_name: str,
    fallback_name: str = "",
    fallback_prefix: str,
    task_uuid: str,
) -> str:
    name = str(preferred_name or "").strip()
    suffix = _safe_suffix(name) or _safe_suffix(str(fallback_name or "").strip())
    if suffix:
        return f"{fallback_prefix}_{task_uuid}{suffix}"
    return f"{fallback_prefix}_{task_uuid}"


def _safe_suffix(name: str) -> str:
    if not name or len(name) > 255:
        return ""
    basename = name.replace("\\", "/").rsplit("/", 1)[-1].split("?", 1)[0]
    basename = basename.split("#", 1)[0]
    suffixes = Path(basename).suffixes[-2:]
    suffix = "".join(suffixes).lower()
    if len(suffix) > 16:
        suffix = Path(suffix).suffix.lower()
    if not suffix or len(suffix) > 16:
        return ""
    if any(ch not in ".abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in suffix):
        return ""
    return suffix


def _download_prefix(record: Any | None = None) -> str:
    if record is None:
        return "file"
    kind = str(getattr(record, "media_type", "") or getattr(record, "kind", ""))
    return "image" if kind.strip().lower() == "image" else "file"


def _is_http_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _is_file_uri(value: str) -> bool:
    return value.startswith("file://")


def _can_treat_as_local_path(value: str) -> bool:
    if not value or len(value) > _MAX_PATH_SOURCE_LENGTH:
        return False
    lowered = value.lower()
    if lowered.startswith(("base64://", "data:")):
        return False
    if "://" in value and not _is_file_uri(value):
        return False
    return True


async def _copy_file_to_temp(
    source: Path,
    target: Path,
) -> None:
    async with aiofiles.open(source, "rb") as src:
        async with aiofiles.open(target, "wb") as dst:
            while True:
                chunk = await src.read(1024 * 1024)
                if not chunk:
                    break
                await dst.write(chunk)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """下载指定文件到临时缓存目录

    参数:
        args: 包含 file_source (URL 或 file_id) 和可选 max_size_mb
        context: 包含回调函数的上下文

    返回:
        下载后的本地磁盘路径或错误信息
    """
    file_source: str = args.get("file_source", "")
    max_size_mb: float = args.get("max_size_mb", 100)

    if not file_source:
        return "错误：文件源不能为空"

    task_uuid: str = uuid.uuid4().hex[:16]

    download_cache_dir_raw = context.get("download_cache_dir")
    ensure_dir_fn = context.get("ensure_dir_fn")
    if download_cache_dir_raw is None or not callable(ensure_dir_fn):
        return "错误：download_file 缺少下载缓存目录上下文依赖"

    download_cache_dir = Path(download_cache_dir_raw)
    temp_dir: Path = cast(Callable[[Path], Path], ensure_dir_fn)(
        download_cache_dir / task_uuid
    )

    attachment_registry = context.get("attachment_registry")
    scope_key = str(context.get("scope_key") or "").strip() or None
    if scope_key is None:
        get_scope_from_context = context.get("get_scope_from_context")
        if callable(get_scope_from_context):
            scope_key_raw = get_scope_from_context(context)
            scope_key = str(scope_key_raw or "").strip() or None
    if attachment_registry and scope_key:
        try:
            load = getattr(attachment_registry, "load", None)
            if load is not None:
                await load()
            resolve_async = getattr(attachment_registry, "resolve_async", None)
            if resolve_async is not None:
                record = await resolve_async(file_source, scope_key)
            else:
                record = attachment_registry.resolve(file_source, scope_key)
        except Exception:
            logger.exception("附件 UID 解析失败: %s", file_source)
            record = None
        if record is not None:
            return await _download_from_attachment_record(
                record,
                registry=attachment_registry,
                temp_dir=temp_dir,
                max_size_mb=max_size_mb,
                task_uuid=task_uuid,
            )

    is_url: bool = _is_http_url(file_source)

    if is_url:
        return await _download_from_url(file_source, temp_dir, max_size_mb, task_uuid)
    else:
        return await _download_from_file_id(file_source, temp_dir, context, task_uuid)


async def _download_from_url(
    url: str, temp_dir: Path, max_size_mb: float, task_uuid: str
) -> str:
    """从 Web URL 进行下载，包含大小预检"""
    max_size_bytes: int = int(max_size_mb * 1024 * 1024)

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            logger.info(f"正在获取文件大小: {url}")
            head_response = await client.head(url, timeout=30.0)
            content_length = head_response.headers.get("content-length")

            if content_length is None:
                return "错误：无法获取文件大小，拒绝下载"

            file_size = int(content_length)
            if file_size > max_size_bytes:
                return f"错误：文件大小 ({file_size / 1024 / 1024:.2f}MB) 超过限制 ({max_size_mb}MB)"

            logger.info(f"文件大小: {file_size / 1024 / 1024:.2f}MB，允许下载")

            logger.info("正在下载文件...")
            response = await client.get(url, timeout=120.0)
            response.raise_for_status()

            filename = _safe_download_filename(
                preferred_name=_extract_filename_from_url(url),
                fallback_prefix="file",
                task_uuid=task_uuid,
            )
            file_path = temp_dir / filename
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(response.content)

            logger.info(f"文件已保存到: {file_path}")
            return str(file_path)

        except httpx.TimeoutException:
            return "错误：下载超时"
        except httpx.HTTPStatusError as e:
            return f"错误：HTTP 错误 {e.response.status_code}"
        except Exception as e:
            logger.exception(f"下载失败: {e}")
            return "错误：下载失败"


async def _download_from_file_id(
    file_id: str, temp_dir: Path, context: Dict[str, Any], task_uuid: str
) -> str:
    """从 OneBot file_id 进行下载或解析"""
    get_image_url_callback = context.get("get_image_url_callback")
    if not get_image_url_callback:
        return "错误：file_id 模式需要 get_image_url_callback"

    try:
        logger.info(f"正在解析 file_id: {file_id}")
        url = await get_image_url_callback(file_id)
        if not url:
            return f"错误：无法将 file_id {file_id} 解析为 URL"

        logger.info(f"获取到 URL: {url}")

        # 检查是否为 HTTP/HTTPS URL
        is_http_url = _is_http_url(url)

        if is_http_url:
            # 使用 httpx 下载远程文件
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(url, timeout=120.0)
                response.raise_for_status()

                filename = _safe_download_filename(
                    preferred_name=file_id,
                    fallback_prefix="file",
                    task_uuid=task_uuid,
                )
                file_path = temp_dir / filename
                async with aiofiles.open(file_path, "wb") as f:
                    await f.write(response.content)

                logger.info(f"文件已保存到: {file_path}")
                return str(file_path)
        else:
            if not _can_treat_as_local_path(url):
                return "错误：解析结果不是可访问的本地文件路径或 HTTP URL"
            # 处理本地文件路径
            local_path = Path(url[7:] if _is_file_uri(url) else url)
            if not local_path.exists():
                return f"错误：本地文件不存在: {url}"

            # 使用 aiofiles 读取本地文件
            async with aiofiles.open(local_path, "rb") as f:
                content = await f.read()

            filename = _safe_download_filename(
                preferred_name=local_path.name,
                fallback_prefix="file",
                task_uuid=task_uuid,
            )
            file_path = temp_dir / filename
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(content)

            logger.info(f"本地文件已复制到: {file_path}")
            return str(file_path)

    except Exception as e:
        logger.exception(f"下载失败（file_id 模式）: {e}")
        return "错误：下载失败，请检查 file_id 或网络状态"


def _extract_filename_from_url(url: str) -> str:
    if "?" in url:
        url = url.split("?")[0]
    filename = url.split("/")[-1]
    return filename


async def _download_from_attachment_record(
    record: Any,
    *,
    registry: Any,
    temp_dir: Path,
    max_size_mb: float,
    task_uuid: str,
) -> str:
    max_size_bytes: int = int(max_size_mb * 1024 * 1024)
    try:
        ensure_local_file = getattr(registry, "ensure_local_file", None)
        if ensure_local_file is not None:
            record = await ensure_local_file(record)

        source_ref = str(getattr(record, "source_ref", "") or "").strip()
        local_path_raw = str(getattr(record, "local_path", "") or "").strip()
        if not _can_treat_as_local_path(local_path_raw):
            if _is_http_url(source_ref):
                return await _download_from_url(
                    source_ref, temp_dir, max_size_mb, task_uuid
                )
            return f"错误：无法从附件 UID {getattr(record, 'uid', '')} 解析到可下载文件"

        local_path = Path(
            local_path_raw[7:] if _is_file_uri(local_path_raw) else local_path_raw
        )
        if not await asyncio.to_thread(local_path.is_file):
            if _is_http_url(source_ref):
                return await _download_from_url(
                    source_ref, temp_dir, max_size_mb, task_uuid
                )
            return f"错误：附件 UID 本地文件不存在：{getattr(record, 'uid', '')}"

        size = await asyncio.to_thread(lambda: local_path.stat().st_size)
        if size > max_size_bytes:
            return (
                f"错误：文件大小 ({size / 1024 / 1024:.2f}MB) "
                f"超过限制 ({max_size_mb}MB)"
            )

        display_name = str(getattr(record, "display_name", "") or "").strip()
        filename = _safe_download_filename(
            preferred_name=display_name,
            fallback_name=local_path.name,
            fallback_prefix=_download_prefix(record),
            task_uuid=task_uuid,
        )
        target = temp_dir / filename
        await _copy_file_to_temp(local_path, target)
        logger.info("附件 UID 已通过注册表复制到: %s", target)
        return str(target)
    except OSError as exc:
        logger.warning(
            "附件 UID 本地化复制失败 uid=%s err=%s",
            getattr(record, "uid", ""),
            exc,
        )
        return "错误：附件文件读取失败"

    return f"错误：无法从附件 UID {getattr(record, 'uid', '')} 解析到可下载文件"
