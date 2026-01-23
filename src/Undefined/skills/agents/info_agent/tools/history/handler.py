from typing import Any, Dict
import logging
import httpx

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            logger.info("获取历史上的今天")

            response = await client.get("https://v2.xxapi.cn/api/history")
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                return f"获取历史事件失败: {data.get('msg')}"

            history_list = data.get("data", [])
            if not history_list:
                return "暂无历史事件数据"

            result = "【历史上的今天】\n\n"

            for idx, event in enumerate(history_list, 1):
                result += f"{idx}. {event}\n"

            return result

    except httpx.TimeoutException:
        return "请求超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        return f"获取历史事件失败: {e}"
    except Exception as e:
        logger.exception(f"获取历史事件失败: {e}")
        return f"获取历史事件失败: {e}"
