from typing import Any, Dict
import httpx
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    mid = args.get("mid")
    url = "https://api.xingzhige.com/API/b_personal/"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params={"mid": mid})
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict):
                if "code" in data and data["code"] != 0 and data["code"] != 200:
                    # 某些 API 返回 code 0 表示成功，其他返回 200。
                    # 但是检查是否有错误信息。
                    if "message" in data:
                        # 可能是一个错误
                        pass

                name = data.get("name")
                level = data.get("level")
                sex = data.get("sex")
                desc = data.get("desc")
                follower = data.get("follower")
                following = data.get("following")
                roomid = data.get("roomid")
                face = data.get("face")

                output_lines = []

                header = "📺 B站用户"
                if name:
                    header += f": {name}"
                if data.get("mid"):
                    header += f" (UID: {data.get('mid')})"
                output_lines.append(header)

                if level is not None:
                    output_lines.append(f"🆙 等级: Lv{level}")

                if sex:
                    output_lines.append(f"⚧ 性别: {sex}")

                if desc:
                    output_lines.append(f"📝 简介: {desc}")

                if follower is not None and following is not None:
                    output_lines.append(f"👥 粉丝: {follower} | 关注: {following}")

                if roomid:
                    output_lines.append(f"🎥 直播间: {roomid}")

                if face:
                    output_lines.append(f"🖼️ 头像: {face}")

                return "\n".join(output_lines)

            return str(data)

    except Exception as e:
        logger.exception(f"B站用户查询失败: {e}")
        return f"B站用户查询失败: {e}"
