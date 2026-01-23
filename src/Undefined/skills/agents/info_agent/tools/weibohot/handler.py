from typing import Any, Dict
import logging
import httpx

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    limit = args.get("limit", 10)

    if limit < 1 or limit > 50:
        return "❌ 热搜数量必须在 1-50 之间"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            logger.info(f"获取微博热搜，数量: {limit}")

            response = await client.get("https://v2.xxapi.cn/api/weibohot")
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                return f"获取微博热搜失败: {data.get('msg')}"

            hot_list = data.get("data", [])
            if not hot_list:
                return "暂无热搜数据"

            result = f"【微博热搜 TOP {min(limit, len(hot_list))}】\n\n"

            for idx, item in enumerate(hot_list[:limit], 1):
                title = item.get("title", "")
                hot = item.get("hot", "")
                url = item.get("url", "")
                result += f"{idx}. {title}\n"
                result += f"   热度: {hot}\n"
                if url:
                    result += f"   链接: {url}\n"
                result += "\n"

            return result

    except httpx.TimeoutException:
        return "请求超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        return f"获取微博热搜失败: {e}"
    except Exception as e:
        logger.exception(f"获取微博热搜失败: {e}")
        return f"获取微博热搜失败: {e}"
