from typing import Any, Dict
import logging
import httpx

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    text = args.get("text")
    operation = args.get("operation")

    if not text:
        return "❌ 文本不能为空"
    if not operation:
        return "❌ 操作类型不能为空"
    if operation not in ["encode", "decode"]:
        return "❌ 操作类型必须是 encode（加密）或 decode（解密）"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            params = {"type": operation, "text": text}
            logger.info(f"Base64 {operation}: {text[:50]}...")

            response = await client.get("https://v2.xxapi.cn/api/base64", params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200 and data.get("code") != "200":
                return f"Base64 {operation} 失败: {data.get('msg')}"

            result = data.get("data")
            operation_text = "加密" if operation == "encode" else "解密"
            return f"Base64{operation_text}结果：\n{result}"

    except httpx.TimeoutException:
        return "请求超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        return f"请求失败: {e}"
    except Exception as e:
        logger.exception(f"Base64操作失败: {e}")
        return f"操作失败: {e}"
