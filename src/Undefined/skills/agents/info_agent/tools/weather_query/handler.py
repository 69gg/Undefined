import os
import aiohttp
import logging
from typing import Dict, Any, cast

logger = logging.getLogger(__name__)

API_KEY = os.getenv("WEATHER_API_KEY", "")
BASE_URL = "https://api.seniverse.com/v3"


async def fetch_data(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if not API_KEY:
        logger.error("WEATHER_API_KEY 未设置")
        return {"error": "天气服务未配置API密钥"}

    params["key"] = API_KEY
    params["language"] = "zh-Hans"
    params["unit"] = "c"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"天气 API 错误: {response.status} - {error_text}")
                return {"error": f"API请求失败: {response.status}"}
            json_data = await response.json()
            return cast(Dict[str, Any], json_data)


async def get_weather_now(location: str) -> str:
    url = f"{BASE_URL}/weather/now.json"
    data = await fetch_data(url, {"location": location})

    if "error" in data:
        return str(data["error"])

    if not data.get("results"):
        return "未找到该城市的天气信息。"

    results = cast(list[dict[str, Any]], data["results"])
    result = results[0]
    loc = cast(dict[str, Any], result["location"])
    now = cast(dict[str, Any], result["now"])
    update_time = str(result["last_update"]).split("T")[1].split("+")[0]

    msg = [f"【{loc['name']} 天气实况】"]

    if "text" in now:
        msg.append(f"天气: {now['text']}")
    if "temperature" in now:
        msg.append(f"温度: {now['temperature']}°C")

    if "feels_like" in now:
        msg.append(f"体感: {now['feels_like']}°C")
    if "humidity" in now:
        msg.append(f"湿度: {now['humidity']}%")
    if "wind_direction" in now:
        wind_dir = str(now["wind_direction"])
        if "wind_direction_degree" in now:
            wind_dir += f" ({now['wind_direction_degree']}°)"
        msg.append(f"风向: {wind_dir}")
    elif "wind_direction_degree" in now:
        msg.append(f"风向: {now['wind_direction_degree']}°")

    if "wind_speed" in now:
        msg.append(f"风速: {now['wind_speed']}km/h")
    if "wind_scale" in now:
        msg.append(f"风力等级: {now['wind_scale']}")
    if "visibility" in now:
        msg.append(f"能见度: {now['visibility']}km")

    msg.append(f"更新时间: {update_time}")

    return "\n".join(msg)


async def get_weather_forecast(location: str) -> str:
    url = f"{BASE_URL}/weather/daily.json"
    # start=0 包括今天。days=5 为请求的范围。
    data = await fetch_data(url, {"location": location, "start": "0", "days": "5"})

    if "error" in data:
        return str(data["error"])

    if not data.get("results"):
        return "未找到该城市的天气预报。"

    results = cast(list[dict[str, Any]], data["results"])
    result = results[0]
    loc_name = str(result["location"]["name"])
    daily_data = cast(list[dict[str, Any]], result["daily"])

    msg = [f"【{loc_name} 未来天气预报】"]
    for day in daily_data:
        date = day.get("date", "未知日期")
        text_day = day.get("text_day")
        text_night = day.get("text_night")
        high = day.get("high")
        low = day.get("low")
        precip = day.get("precip")
        wind_scale = day.get("wind_scale")

        day_info = [f"{date}:"]
        if text_day and text_night:
            weather_str = (
                text_day if text_day == text_night else f"{text_day}转{text_night}"
            )
            day_info.append(str(weather_str))
        elif text_day:
            day_info.append(str(text_day))

        if low is not None and high is not None:
            day_info.append(f"{low}~{high}°C")

        if precip:
            day_info.append(f"降水概率{precip}%")

        if wind_scale:
            day_info.append(f"风力{wind_scale}级")

        msg.append(" ".join(day_info))

    return "\n".join(msg)


async def get_life_suggestion(location: str) -> str:
    url = f"{BASE_URL}/life/suggestion.json"
    data = await fetch_data(url, {"location": location})

    if "error" in data:
        return str(data["error"])

    if not data.get("results"):
        return "未找到该城市的生活指数信息。"

    results = cast(list[dict[str, Any]], data["results"])
    result = results[0]
    loc_name = str(result["location"]["name"])
    suggestion = cast(dict[str, Any], result.get("suggestion", {}))

    label_map = {
        "ac": "空调开启",
        "air_pollution": "空气扩散",
        "airing": "晾晒",
        "allergy": "过敏",
        "beer": "啤酒",
        "boating": "划船",
        "car_washing": "洗车",
        "chill": "风寒",
        "comfort": "舒适度",
        "dating": "约会",
        "dressing": "穿衣",
        "fishing": "钓鱼",
        "flu": "感冒",
        "hair_dressing": "美发",
        "kiteflying": "放风筝",
        "makeup": "化妆",
        "mood": "心情",
        "morning_sport": "晨练",
        "night_life": "夜生活",
        "road_condition": "路况",
        "shopping": "购物",
        "sport": "运动",
        "sunscreen": "防晒",
        "traffic": "交通",
        "travel": "旅游",
        "umbrella": "雨伞",
        "uv": "紫外线",
    }

    msg = [f"【{loc_name} 生活指数】"]

    for key, info_raw in suggestion.items():
        info = cast(dict[str, Any], info_raw)
        if not info or not info.get("brief"):
            continue

        label = label_map.get(key, key)
        brief = info["brief"]
        msg.append(f"{label}: {brief}")

    if len(msg) == 1:
        return f"【{loc_name}】暂无生活指数信息。"

    return "\n".join(msg)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    location = args.get("location")
    query_type = args.get("query_type", "now")

    if not location:
        return "请提供城市名称。"

    try:
        if query_type == "forecast":
            return await get_weather_forecast(location)
        elif query_type == "life":
            return await get_life_suggestion(location)
        else:
            # 默认为当前天气
            return await get_weather_now(location)

    except Exception as e:
        logger.exception(f"天气查询工具出错: {e}")
        return f"查询出错: {str(e)}"
