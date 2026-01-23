from typing import Any, Dict
import logging
import httpx

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    url = args.get("url")

    if not url:
        return "❌ URL不能为空"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            params = {"url": url}
            logger.info(f"网站测速: {url}")

            response = await client.get("https://v2.xxapi.cn/api/speed", params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                return f"测速失败: {data.get('msg')}"

            result = data.get("data")
            return f"网站 {url} 响应时间：\n{result}"

    except httpx.TimeoutException:
        return "请求超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        return f"测速失败: {e}"
    except Exception as e:
        logger.exception(f"网站测速失败: {e}")
        return f"测速失败: {e}"
