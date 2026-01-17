from typing import Any, Dict
import httpx
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    name = args.get("name")
    href = args.get("href")
    num = args.get("num")

    url = "https://api.jkyai.top/API/fqmfxs.php"
    params = {}
    if name:
        params["name"] = name
    if href:
        params["href"] = href
    if num:
        params["num"] = num

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params=params)

            # API 返回文本
            return response.text

    except Exception as e:
        logger.exception(f"小说工具操作失败: {e}")
        return f"小说工具操作失败: {e}"
