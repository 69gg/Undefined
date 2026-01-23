from typing import Any, Dict
import logging
import httpx

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    address = args.get("address")
    port = args.get("port")

    if not address:
        return "❌ 地址不能为空"
    if not port:
        return "❌ 端口不能为空"
    if not isinstance(port, int):
        return "❌ 端口必须是整数"
    if port < 1 or port > 65535:
        return "❌ 端口必须在 1-65535 之间"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            params = {"address": address, "port": port}
            logger.info(f"TCPing: {address}:{port}")

            response = await client.get("https://v2.xxapi.cn/api/tcping", params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                return f"TCPing失败: {data.get('msg')}"

            result_data = data.get("data", {})
            ping_result = result_data.get("ping")
            result_address = result_data.get("address", address)
            result_port = result_data.get("port", port)

            output_lines = [
                "TCPing测试结果：",
                f"地址：{result_address}",
                f"端口：{result_port}",
            ]
            if ping_result:
                output_lines.append(f"延迟：{ping_result}")

            return "\n".join(output_lines)

    except httpx.TimeoutException:
        return "请求超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        return f"TCPing失败: {e}"
    except Exception as e:
        logger.exception(f"TCPing失败: {e}")
        return f"TCPing失败: {e}"
