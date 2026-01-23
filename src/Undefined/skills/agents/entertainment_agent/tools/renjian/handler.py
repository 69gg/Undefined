from typing import Any, Dict
import logging
import httpx

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            logger.info("获取人间凑数语录")

            response = await client.get("https://v2.xxapi.cn/api/renjian")
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                return f"获取语录失败: {data.get('msg')}"

            quote = data.get("data", "")

            return f"【在人间凑数的日子】\n{quote}"

    except httpx.TimeoutException:
        return "请求超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        return f"获取语录失败: {e}"
    except Exception as e:
        logger.exception(f"获取语录失败: {e}")
        return f"获取语录失败: {e}"
