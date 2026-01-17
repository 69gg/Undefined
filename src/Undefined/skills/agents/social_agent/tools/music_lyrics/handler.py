from typing import Any, Dict
import httpx
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    song_id = args.get("id")
    platform = args.get("msg")

    url = "https://api.jkyai.top/API/jhlrcgc.php"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                url, params={"id": song_id, "msg": platform, "type": "text"}
            )
            # API 文档说明 type 是可选的，默认为 text。
            # 如果是 text，它可能直接返回歌词。

            return f"🎵 歌词内容:\n{response.text}"

    except Exception as e:
        logger.exception(f"获取歌词失败: {e}")
        return f"获取歌词失败: {e}"
