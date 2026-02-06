from typing import Any, Dict
import logging
import httpx

from Undefined.skills.http_config import get_request_timeout, get_xxapi_url

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """向文昌帝君祈福，获取一段励志或考试相关的祝福语"""
    try:
        timeout = get_request_timeout(10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            logger.info("抽取文昌帝君灵签")

            response = await client.get(get_xxapi_url("/api/wenchangdijunrandom"))
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                return f"抽签失败: {data.get('msg')}"

            fortune_data = data.get("data", {})
            title = fortune_data.get("title", "")
            poem = fortune_data.get("poem", "")
            content = fortune_data.get("content", "")
            pic = fortune_data.get("pic", "")
            fortune_id = fortune_data.get("id", "")

            result = "【文昌帝君灵签】\n"
            result += f"签号：{fortune_id}\n"
            result += f"签名：{title}\n\n"
            result += f"【签诗】\n{poem}\n\n"
            result += f"【签文】\n{content}\n"

            if pic:
                result += f"\n签文图片：{pic}"

            return result

    except httpx.TimeoutException:
        return "请求超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        return f"抽签失败: {e}"
    except Exception as e:
        logger.exception(f"文昌帝君抽签失败: {e}")
        return f"抽签失败: {e}"
