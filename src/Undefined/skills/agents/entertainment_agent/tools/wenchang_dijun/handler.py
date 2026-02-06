from typing import Any, Dict
import logging
import httpx

from Undefined.skills.http_client import get_json_with_retry
from Undefined.skills.http_config import get_xxapi_url

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """向文昌帝君祈福，获取一段励志或考试相关的祝福语"""
    try:
        logger.info("抽取文昌帝君灵签")
        data = await get_json_with_retry(
            get_xxapi_url("/api/wenchangdijunrandom"),
            default_timeout=10.0,
            context=context,
        )

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
        return "抽签失败：网络请求错误"
    except Exception as e:
        logger.exception(f"文昌帝君抽签失败: {e}")
        return "抽签失败，请稍后重试"
