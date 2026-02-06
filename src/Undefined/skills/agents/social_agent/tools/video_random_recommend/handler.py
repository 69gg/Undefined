from typing import Any, Dict
import logging

from Undefined.skills.http_client import request_with_retry
from Undefined.skills.http_config import get_jkyai_url

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """随机推荐一段短视频（如抖音、快手等热门内容）"""
    url = get_jkyai_url("/API/jxhssp.php")

    try:
        response = await request_with_retry(
            "GET",
            url,
            default_timeout=15.0,
            follow_redirects=True,
            context=context,
        )
        # 我们只需要最终的 URL，所以读取响应最终地址。
        final_url = str(response.url)
        return f"🎥 随机视频推荐:\n{final_url}"

    except Exception as e:
        logger.exception(f"获取视频失败: {e}")
        return f"获取视频失败: {e}"
