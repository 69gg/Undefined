import uuid
from pathlib import Path
from typing import Any, Dict
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
    from Undefined.utils.paths import DOWNLOAD_CACHE_DIR, ensure_dir

    temp_dir: Path = ensure_dir(DOWNLOAD_CACHE_DIR / task_uuid)

    is_url: bool = file_source.startswith("http://") or file_source.startswith(
        "https://"
    )

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

            filename = _extract_filename_from_url(url)
            if not filename or "." not in filename:
                filename = f"downloaded_{task_uuid}"

            file_path = temp_dir / filename
            file_path.write_bytes(response.content)

            logger.info(f"文件已保存到: {file_path}")
            return str(file_path)

        except httpx.TimeoutException:
            return "错误：下载超时"
        except httpx.HTTPStatusError as e:
            return f"错误：HTTP 错误 {e.response.status_code}"
        except Exception as e:
            logger.exception(f"下载失败: {e}")
            return f"错误：下载失败 - {e}"


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
        is_http_url = url.startswith("http://") or url.startswith("https://")

        if is_http_url:
            # 使用 httpx 下载远程文件
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(url, timeout=120.0)
                response.raise_for_status()

                filename = f"file_{file_id}"
                file_path = temp_dir / filename
                file_path.write_bytes(response.content)

                logger.info(f"文件已保存到: {file_path}")
                return str(file_path)
        else:
            # 处理本地文件路径
            local_path = Path(url)
            if not local_path.exists():
                return f"错误：本地文件不存在: {url}"

            # 使用 aiofiles 读取本地文件
            async with aiofiles.open(local_path, "rb") as f:
                content = await f.read()

            filename = local_path.name
            file_path = temp_dir / filename
            file_path.write_bytes(content)

            logger.info(f"本地文件已复制到: {file_path}")
            return str(file_path)

    except Exception as e:
        logger.exception(f"下载失败（file_id 模式）: {e}")
        return f"错误：下载失败 - {e}"


def _extract_filename_from_url(url: str) -> str:
    if "?" in url:
        url = url.split("?")[0]
    filename = url.split("/")[-1]
    return filename
