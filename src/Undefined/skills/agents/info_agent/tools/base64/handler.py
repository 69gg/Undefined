from typing import Any, Dict
import logging
import httpx

from Undefined.skills.http_client import get_json_with_retry
from Undefined.skills.http_config import get_xxapi_url

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """对字符串进行 Base64 编码或解码操作"""
    text = args.get("text")
    operation = args.get("operation")

    if not text:
        return "❌ 文本不能为空"
    if not operation:
        return "❌ 操作类型不能为空"
    if operation not in ["encode", "decode"]:
        return "❌ 操作类型必须是 encode（加密）或 decode（解密）"

    try:
        params = {"type": operation, "text": text}
        logger.info(f"Base64 {operation}: {text[:50]}...")
        data = await get_json_with_retry(
            get_xxapi_url("/api/base64"),
            params=params,
            default_timeout=10.0,
            context=context,
        )

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
