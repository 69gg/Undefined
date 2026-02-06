from typing import Any, Dict
import logging

from Undefined.skills.http_client import get_json_with_retry
from Undefined.skills.http_config import get_xingzhige_url

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """查询指定 QQ 号的等级、活跃天数及升级进度"""
    params = {
        "qq": args.get("qq"),
        "uin": args.get("uin"),
        "skey": args.get("skey"),
        "pskey": args.get("pskey"),
    }
    url = get_xingzhige_url("/API/QQ_level/")

    try:
        data = await get_json_with_retry(
            url,
            params=params,
            default_timeout=15.0,
            context=context,
        )

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
