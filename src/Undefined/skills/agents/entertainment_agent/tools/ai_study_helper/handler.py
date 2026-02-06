from typing import Any, Dict
import logging

from Undefined.skills.http_client import get_json_with_retry
from Undefined.skills.http_config import get_jkyai_url

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    question = args.get("question")
    content = args.get("content", "yes")

    url = get_jkyai_url("/API/wnjtzs.php")

    try:
        data = await get_json_with_retry(
            url,
            params={"question": question, "content": content, "type": "json"},
            default_timeout=60.0,
            context=context,
        )

        # 格式化
        status = data.get("status")
        if status != "success":
            return f"AI 响应失败: {status}"

        q = data.get("question", "")
        ans = data.get("answer", "")
        model = data.get("model", "")

        return f"🤖 AI 解答 ({model}):\n❓ 问题: {q}\n💡 答案: {ans}"

    except Exception as e:
        logger.exception(f"AI 助手请求失败: {e}")
        return f"AI 助手请求失败: {e}"
