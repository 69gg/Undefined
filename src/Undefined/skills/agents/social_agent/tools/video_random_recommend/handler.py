from typing import Any, Dict
import httpx
import logging

from Undefined.skills.http_config import get_jkyai_url, get_request_timeout

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """随机推荐一段短视频（如抖音、快手等热门内容）"""
    url = get_jkyai_url("/API/jxhssp.php")

    try:
        timeout = get_request_timeout(15.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            # 我们只需要最终的 URL，所以我们触发请求并检查历史或 url
            response = await client.get(url)
            final_url = str(response.url)

            return f"🎥 随机视频推荐:\n{final_url}"

    except Exception as e:
        logger.exception(f"获取视频失败: {e}")
        return f"获取视频失败: {e}"
