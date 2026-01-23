from typing import Any, Dict
import logging
import httpx

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    limit = args.get("limit", 10)

    if limit < 1 or limit > 50:
        return "❌ 热榜数量必须在 1-50 之间"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            logger.info(f"获取抖音热榜，数量: {limit}")

            response = await client.get("https://v2.xxapi.cn/api/douyinhot")
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                return f"获取抖音热榜失败: {data.get('msg')}"

            hot_list = data.get("data", [])
            if not hot_list:
                return "暂无热榜数据"

            result = f"【抖音热榜 TOP {min(limit, len(hot_list))}】\n\n"

            for idx, item in enumerate(hot_list[:limit], 1):
                word = item.get("word", "")
                hot_value = item.get("hot_value", 0)
                position = item.get("position", idx)
                video_count = item.get("video_count", 0)

                # 将热度值转换为万
                hot_str = (
                    f"{hot_value / 10000:.1f}万"
                    if hot_value >= 10000
                    else str(hot_value)
                )

                result += f"{position}. {word}\n"
                result += f"   热度: {hot_str}\n"
                result += f"   视频数: {video_count}\n"
                result += "\n"

            return result

    except httpx.TimeoutException:
        return "请求超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        return f"获取抖音热榜失败: {e}"
    except Exception as e:
        logger.exception(f"获取抖音热榜失败: {e}")
        return f"获取抖音热榜失败: {e}"
