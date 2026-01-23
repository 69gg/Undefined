from typing import Any, Dict
import logging
import httpx

logger = logging.getLogger(__name__)

# 星座名称映射（中文 -> 英文）
CONSTELLATION_MAP = {
    "白羊座": "aries",
    "金牛座": "taurus",
    "双子座": "gemini",
    "巨蟹座": "cancer",
    "狮子座": "leo",
    "处女座": "virgo",
    "天秤座": "libra",
    "天蝎座": "scorpio",
    "射手座": "sagittarius",
    "摩羯座": "capricorn",
    "水瓶座": "aquarius",
    "双鱼座": "pisces",
}

# 时间类型映射（中文 -> 英文）
TIME_TYPE_MAP = {
    "今日": "today",
    "本周": "week",
    "本月": "month",
    "本年": "year",
}

# 星座星级显示
STAR_MAP = {1: "★", 2: "★★", 3: "★★★", 4: "★★★★", 5: "★★★★★"}


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    constellation = args.get("constellation")
    time_type = args.get("time_type", "today")

    if not constellation:
        return "❌ 星座不能为空"

    # 转换星座名称为英文
    constellation_en = CONSTELLATION_MAP.get(constellation, constellation)
    if constellation_en not in CONSTELLATION_MAP.values():
        return f"❌ 不支持的星座: {constellation}\n支持的星座: {', '.join(CONSTELLATION_MAP.keys())}"

    # 转换时间类型为英文
    time_type_en = TIME_TYPE_MAP.get(time_type, time_type)
    if time_type_en not in TIME_TYPE_MAP.values():
        return f"❌ 不支持的时间类型: {time_type}\n支持的时间类型: {', '.join(TIME_TYPE_MAP.keys())}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            params = {"type": constellation_en, "time": time_type_en}
            logger.info(
                f"获取星座运势: {constellation} ({constellation_en}), 时间: {time_type} ({time_type_en})"
            )

            response = await client.get(
                "https://v2.xxapi.cn/api/horoscope", params=params
            )
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                return f"获取运势失败: {data.get('msg')}"

            fortune_data = data.get("data", {})

            # 格式化运势信息
            title = fortune_data.get("title", constellation)
            time_text = fortune_data.get("type", time_type)
            short_comment = fortune_data.get("shortcomment", "")
            date_text = fortune_data.get("time", "")

            # 运势评分
            fortune = fortune_data.get("fortune", {})
            fortune_stars = {
                "综合": STAR_MAP.get(fortune.get("all", 0), ""),
                "健康": STAR_MAP.get(fortune.get("health", 0), ""),
                "爱情": STAR_MAP.get(fortune.get("love", 0), ""),
                "财运": STAR_MAP.get(fortune.get("money", 0), ""),
                "工作": STAR_MAP.get(fortune.get("work", 0), ""),
            }

            # 运势指数
            index = fortune_data.get("index", {})

            # 运势文本
            fortunetext = fortune_data.get("fortunetext", {})

            # 幸运信息
            lucky_color = fortune_data.get("luckycolor", "")
            lucky_constellation = fortune_data.get("luckyconstellation", "")
            lucky_number = fortune_data.get("luckynumber", "")

            # 宜忌
            todo = fortune_data.get("todo", {})
            todo_yi = todo.get("ji", "")
            todo_ji = todo.get("yi", "")

            # 构建结果
            result = f"【{title} {time_text}】{date_text}\n"
            result += f"短评：{short_comment}\n\n"

            result += "【运势评分】\n"
            for name, stars in fortune_stars.items():
                result += f"{name}：{stars}\n"
            result += "\n"

            result += "【运势指数】\n"
            for name, value in index.items():
                result += f"{name}：{value}\n"
            result += "\n"

            result += "【运势详情】\n"
            for name, text in fortunetext.items():
                result += f"{name}：{text}\n"
            result += "\n"

            result += "【幸运信息】\n"
            result += f"幸运色：{lucky_color}\n"
            result += f"幸运星座：{lucky_constellation}\n"
            result += f"幸运数字：{lucky_number}\n"
            result += "\n"

            if todo_yi or todo_ji:
                result += "【宜忌】\n"
                if todo_yi:
                    result += f"宜：{todo_yi}\n"
                if todo_ji:
                    result += f"忌：{todo_ji}\n"

            return result

    except httpx.TimeoutException:
        return "获取运势超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        return f"获取运势失败: {e}"
    except Exception as e:
        logger.exception(f"获取星座运势失败: {e}")
        return f"获取运势失败: {e}"
