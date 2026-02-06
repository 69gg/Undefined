from typing import Any, Dict
import httpx
import logging

from Undefined.skills.http_config import get_jkyai_url, get_request_timeout

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """在全球范围内搜索指定关键词的音乐资源"""
    msg = args.get("msg")
    n = args.get("n", 1)

    url = get_jkyai_url("/API/qsyyjs.php")

    try:
        timeout = get_request_timeout(15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                url, params={"msg": msg, "n": n, "type": "json"}
            )
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict):
                output_lines = []

                title = data.get("title")
                if title:
                    output_lines.append(f"🎵 音乐搜索: {title}")

                singer = data.get("singer")
                if singer:
                    output_lines.append(f"👤 歌手: {singer}")

                music_url = data.get("music")
                if music_url:
                    output_lines.append(f"🔗 链接: {music_url}")

                cover = data.get("cover")
                if cover:
                    output_lines.append(f"🖼️ 封面: {cover}")

                if output_lines:
                    return "\n".join(output_lines)
                else:
                    return "未找到相关音乐信息。"

            return str(data)

    except Exception as e:
        logger.exception(f"音乐搜索失败: {e}")
        return f"音乐搜索失败: {e}"
