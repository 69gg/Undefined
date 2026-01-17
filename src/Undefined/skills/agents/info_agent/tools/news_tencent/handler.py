from typing import Any, Dict
import httpx
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    page = args.get("page", 10)
    url = "https://api.jkyai.top/API/txxwtt.php"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params={"page": page, "type": "json"})
            response.raise_for_status()
            data = response.json()

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
        logger.exception(f"获取新闻失败: {e}")
        return f"获取新闻失败: {e}"
