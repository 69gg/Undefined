from typing import Any, Dict
import httpx
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    question = args.get("question")
    content = args.get("content", "yes")

    url = "https://api.jkyai.top/API/wnjtzs.php"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                url, params={"question": question, "content": content, "type": "json"}
            )
            response.raise_for_status()
            data = response.json()

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
