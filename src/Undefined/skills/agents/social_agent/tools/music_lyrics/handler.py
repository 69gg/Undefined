from typing import Any, Dict
import logging

from Undefined.skills.http_client import get_text_with_retry
from Undefined.skills.http_config import get_jkyai_url

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    song_id = args.get("id")
    platform = args.get("msg")

    url = get_jkyai_url("/API/jhlrcgc.php")

    try:
        lyrics = await get_text_with_retry(
            url,
            params={"id": song_id, "msg": platform, "type": "text"},
            default_timeout=15.0,
            context=context,
        )
        # API 文档说明 type 是可选的，默认为 text。
        # 如果是 text，它可能直接返回歌词。
        return f"🎵 歌词内容:\n{lyrics}"

    except Exception as e:
        logger.exception(f"获取歌词失败: {e}")
        return f"获取歌词失败: {e}"
