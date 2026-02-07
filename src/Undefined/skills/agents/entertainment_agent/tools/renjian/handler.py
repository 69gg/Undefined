from typing import Any, Dict
import logging
import httpx

from Undefined.skills.http_client import get_json_with_retry
from Undefined.skills.http_config import get_xxapi_url

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取指定句子的“人间文案”感悟"""
    try:
        logger.info("获取人间凑数语录")
        data = await get_json_with_retry(
            get_xxapi_url("/api/renjian"),
            default_timeout=10.0,
            context=context,
        )

        if data.get("code") != 200:
            return f"获取语录失败: {data.get('msg')}"

        quote = data.get("data", "")

        return f"【在人间凑数的日子】\n{quote}"

    except httpx.TimeoutException:
        return "请求超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        return "获取语录失败：网络请求错误"
    except Exception as e:
        logger.exception(f"获取语录失败: {e}")
        return "获取语录失败，请稍后重试"
