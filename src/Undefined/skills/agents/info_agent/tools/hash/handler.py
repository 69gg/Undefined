from typing import Any, Dict
import logging
import httpx

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    text = args.get("text")
    algorithm = args.get("algorithm")

    if not text:
        return "❌ 文本不能为空"
    if not algorithm:
        return "❌ 算法不能为空"
    if algorithm not in ["md4", "md5", "sha1", "sha256", "sha512"]:
        return "❌ 算法必须是 md4、md5、sha1、sha256 或 sha512"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            params = {"type": algorithm, "text": text}
            logger.info(f"Hash {algorithm}: {text[:50]}...")

            response = await client.get("https://v2.xxapi.cn/api/hash", params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                return f"Hash加密失败: {data.get('msg')}"

            result = data.get("data")
            return f"{algorithm.upper()}加密结果：\n{result}"

    except httpx.TimeoutException:
        return "请求超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        return f"请求失败: {e}"
    except Exception as e:
        logger.exception(f"Hash加密失败: {e}")
        return f"加密失败: {e}"
