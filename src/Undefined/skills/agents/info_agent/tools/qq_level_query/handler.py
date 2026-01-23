from typing import Any, Dict
import httpx
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    params = {
        "qq": args.get("qq"),
        "uin": args.get("uin"),
        "skey": args.get("skey"),
        "pskey": args.get("pskey"),
    }
    url = "https://api.xingzhige.com/API/QQ_level/"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict):
                nick = data.get("nick")
                qq_level = data.get("QQlevel")
                uin = data.get("uin", params["qq"])
                avatar = data.get("avatar")

                output_lines = []

                header = "⭐ QQ等级查询"
                if nick:
                    header += f": {nick}"
                if uin:
                    header += f" ({uin})"
                output_lines.append(header)

                if qq_level:
                    output_lines.append(f"🆙 等级: {qq_level}")

                if avatar:
                    output_lines.append(f"🖼️ 头像: {avatar}")

                return "\n".join(output_lines)
            return str(data)

    except Exception as e:
        logger.exception(f"QQ等级查询失败: {e}")
        return f"QQ等级查询失败: {e}"
