from typing import Any, Dict
import httpx
import logging

from Undefined.skills.http_config import get_jkyai_url, get_request_timeout

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    song_id = args.get("id")
    platform = args.get("type")

    url = get_jkyai_url("/API/yyjhss.php")

    try:
        timeout = get_request_timeout(15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params={"id": song_id, "type": platform})
            response.raise_for_status()
            data = response.json()

            # 数据结构: code, msg, data{name, artist, url, ...}
            if data.get("code") == 1:
                info = data.get("data", {})
                return (
                    f"🎵 歌曲信息: {info.get('name')}\n"
                    f"👤 歌手: {info.get('artist')}\n"
                    f"💿 专辑: {info.get('album')}\n"
                    f"🔗 链接: {info.get('url')}\n"
                    f"🖼️ 图片: {info.get('pic')}"
                )
            else:
                return f"获取失败: {data.get('msg')}"

    except Exception as e:
        logger.exception(f"获取歌曲详情失败: {e}")
        return f"获取歌曲详情失败: {e}"
