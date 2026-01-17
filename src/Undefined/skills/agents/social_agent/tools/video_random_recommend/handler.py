from typing import Any, Dict
import httpx
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    url = "https://api.jkyai.top/API/jxhssp.php"

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            # 我们只需要最终的 URL，所以我们触发请求并检查历史或 url
            response = await client.get(url)
            final_url = str(response.url)

            return f"🎥 随机视频推荐:\n{final_url}"

    except Exception as e:
        logger.exception(f"获取视频失败: {e}")
        return f"获取视频失败: {e}"
