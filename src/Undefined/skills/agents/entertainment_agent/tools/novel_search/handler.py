from typing import Any, Dict
import httpx
import logging

from Undefined.skills.http_config import get_jkyai_url, get_request_timeout

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """在网络上搜索指定小说及其相关链接信息"""
    name = args.get("name")
    href = args.get("href")
    num = args.get("num")

    url = get_jkyai_url("/API/fqmfxs.php")
    params = {}
    if name:
        params["name"] = name
    if href:
        params["href"] = href
    if num:
        params["num"] = num

    try:
        timeout = get_request_timeout(15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=params)

            # API 返回文本
            return response.text

    except Exception as e:
        logger.exception(f"小说工具操作失败: {e}")
        return f"小说工具操作失败: {e}"
