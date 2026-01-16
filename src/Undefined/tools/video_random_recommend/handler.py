from typing import Any, Dict
import httpx
import logging

logger = logging.getLogger(__name__)

async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    url = "https://api.jkyai.top/API/jxhssp.php"
    
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            # We just want the final URL, so we trigger the request and check history or url
            response = await client.get(url)
            final_url = str(response.url)
            
            return f"🎥 随机视频推荐:\n{final_url}"

    except Exception as e:
        logger.exception(f"获取视频失败: {e}")
        return f"获取视频失败: {e}"
