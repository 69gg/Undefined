from typing import Any, Dict
import logging
import httpx

from Undefined.skills.http_client import get_json_with_retry
from Undefined.skills.http_config import get_xxapi_url

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    url = args.get("url")

    if not url:
        return "❌ URL不能为空"

    try:
        params = {"url": url}
        logger.info(f"网站测速: {url}")
        data = await get_json_with_retry(
            get_xxapi_url("/api/speed"),
            params=params,
            default_timeout=30.0,
            context=context,
        )

        if data.get("code") != 200:
            return f"测速失败: {data.get('msg')}"

        result = data.get("data")
        return f"网站 {url} 响应时间：\n{result}"

    except httpx.TimeoutException:
        return "请求超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        return "测速失败：网络请求错误"
    except Exception as e:
        logger.exception(f"网站测速失败: {e}")
        return "测速失败，请稍后重试"
