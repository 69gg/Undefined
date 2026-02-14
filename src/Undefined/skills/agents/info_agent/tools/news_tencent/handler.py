from typing import Any, Dict
import logging

from Undefined.skills.http_client import get_json_with_retry
from Undefined.skills.http_config import get_jkyai_url

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取腾讯新闻的最新实时资讯"""
    page = args.get("page", 10)
    url = get_jkyai_url("/API/txxwtt.php")

    try:
        data = await get_json_with_retry(
            url,
            params={"page": page, "type": "json"},
            default_timeout=15.0,
            context=context,
        )

        # 假设数据是一个列表或带有列表的字典
        if isinstance(data, list):
            news_list = data
        elif isinstance(data, dict) and "data" in data:
            news_list = data["data"]
        else:
            news_list = [data] if data else []

        output = "📰 腾讯新闻头条:\n"
        for item in news_list:
            if isinstance(item, dict):
                title = item.get("title", "")
                url_link = item.get("url", "")
                if title:
                    output += f"- {title}\n  {url_link}\n"

        return output if len(output) > 15 else f"未获取到新闻: {data}"

    except Exception as e:
        logger.warning("获取腾讯新闻失败: page=%s err=%s", page, e)
        logger.debug("获取腾讯新闻异常详情", exc_info=True)
        return "获取新闻失败，请稍后重试"
