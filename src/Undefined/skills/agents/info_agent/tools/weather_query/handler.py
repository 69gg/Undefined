import logging
from typing import Any, Dict

import httpx

from Undefined.skills.http_client import get_json_with_retry

logger = logging.getLogger(__name__)

_WTTR_ENDPOINT = "https://wttr.in"
_WEATHER_CODE_ZH: dict[str, str] = {
    "113": "晴",
    "116": "多云",
    "119": "阴",
    "122": "阴天",
    "143": "雾",
    "176": "小雨",
    "179": "雨夹雪",
    "185": "冻雨",
    "200": "雷暴",
    "227": "小雪",
    "230": "暴风雪",
    "248": "雾",
    "260": "浓雾",
    "263": "零星小雨",
    "266": "小雨",
    "293": "零星小雨",
    "296": "小雨",
    "299": "中雨",
    "302": "大雨",
    "305": "中到大雨",
    "308": "暴雨",
    "311": "冻雨",
    "317": "雨夹雪",
    "320": "雨夹雪",
    "323": "零星小雪",
    "326": "小雪",
    "329": "中雪",
    "332": "大雪",
    "335": "暴雪",
    "338": "暴雪",
    "350": "冰粒",
    "353": "阵雨",
    "356": "中雨",
    "359": "大雨",
    "362": "雨夹雪",
    "365": "雨夹雪",
    "368": "阵雪",
    "371": "大雪",
    "374": "冰粒",
    "377": "冰雹",
    "386": "雷阵雨",
    "389": "强雷阵雨",
    "392": "雷阵雪",
    "395": "雷暴暴雪",
}


def _as_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _to_int(value: Any) -> int | None:
    text = _as_str(value)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _as_list_of_dict(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _first_value(value: Any) -> str:
    items = _as_list_of_dict(value)
    if not items:
        return ""
    return _as_str(items[0].get("value"))


def _extract_city_name(data: dict[str, Any], fallback: str) -> str:
    areas = _as_list_of_dict(data.get("nearest_area"))
    if not areas:
        return fallback

    area = _first_value(areas[0].get("areaName"))
    region = _first_value(areas[0].get("region"))
    if area and region and area != region:
        return f"{region} {area}"
    return area or region or fallback


def _extract_weather_text(entry: dict[str, Any]) -> str:
    weather_code = _as_str(entry.get("weatherCode"))
    if weather_code and weather_code in _WEATHER_CODE_ZH:
        return _WEATHER_CODE_ZH[weather_code]

    text = _first_value(entry.get("weatherDesc"))
    return text or "未知"


def _extract_rain_chance(hourly: list[dict[str, Any]]) -> int | None:
    values: list[int] = []
    for item in hourly:
        chance = _to_int(item.get("chanceofrain"))
        if chance is not None:
            values.append(chance)
    if not values:
        return None
    return max(values)


def _extract_max_wind_speed(hourly: list[dict[str, Any]]) -> int | None:
    values: list[int] = []
    for item in hourly:
        wind = _to_int(item.get("windspeedKmph"))
        if wind is not None:
            values.append(wind)
    if not values:
        return None
    return max(values)


def _pick_mid_hourly(day: dict[str, Any]) -> dict[str, Any]:
    hourly = _as_list_of_dict(day.get("hourly"))
    if not hourly:
        return {}
    return hourly[min(len(hourly) // 2, len(hourly) - 1)]


def _format_error(err: Exception) -> str:
    if isinstance(err, httpx.HTTPStatusError):
        status_code = err.response.status_code
        body = err.response.text.strip()
        if body:
            return f"HTTPStatusError: {status_code} {body}"
        return f"HTTPStatusError: {status_code}"
    return f"{type(err).__name__}: {err}"


async def _fetch_wttr_data(location: str, context: Dict[str, Any]) -> dict[str, Any]:
    city = str(location).strip()
    url = f"{_WTTR_ENDPOINT}/{city}"
    data = await get_json_with_retry(
        url,
        params={"format": "j1"},
        default_timeout=15.0,
        follow_redirects=True,
        context=context,
    )
    if isinstance(data, dict):
        return data
    return {}


async def get_weather_now(location: str, context: Dict[str, Any]) -> str:
    data = await _fetch_wttr_data(location, context)
    current = _as_list_of_dict(data.get("current_condition"))
    if not current:
        return "未找到该城市的天气信息。"

    now = current[0]
    loc_name = _extract_city_name(data, location)
    msg = [f"【{loc_name} 天气实况】"]

    weather_text = _extract_weather_text(now)
    if weather_text:
        msg.append(f"天气: {weather_text}")

    temp_c = _as_str(now.get("temp_C"))
    if temp_c:
        msg.append(f"温度: {temp_c}°C")

    feels_like_c = _as_str(now.get("FeelsLikeC"))
    if feels_like_c:
        msg.append(f"体感: {feels_like_c}°C")

    humidity = _as_str(now.get("humidity"))
    if humidity:
        msg.append(f"湿度: {humidity}%")

    wind_dir = _as_str(now.get("winddir16Point"))
    wind_degree = _as_str(now.get("winddirDegree"))
    if wind_dir:
        if wind_degree:
            msg.append(f"风向: {wind_dir} ({wind_degree}°)")
        else:
            msg.append(f"风向: {wind_dir}")
    elif wind_degree:
        msg.append(f"风向: {wind_degree}°")

    wind_speed = _as_str(now.get("windspeedKmph"))
    if wind_speed:
        msg.append(f"风速: {wind_speed}km/h")

    visibility = _as_str(now.get("visibility"))
    if visibility:
        msg.append(f"能见度: {visibility}km")

    uv_index = _as_str(now.get("uvIndex"))
    if uv_index:
        msg.append(f"紫外线指数: {uv_index}")

    update_time = _as_str(now.get("localObsDateTime")) or _as_str(
        now.get("observation_time")
    )
    if update_time:
        msg.append(f"更新时间: {update_time}")

    return "\n".join(msg)


async def get_weather_forecast(location: str, context: Dict[str, Any]) -> str:
    data = await _fetch_wttr_data(location, context)
    weather = _as_list_of_dict(data.get("weather"))
    if not weather:
        return "未找到该城市的天气预报。"

    loc_name = _extract_city_name(data, location)
    msg = [f"【{loc_name} 未来天气预报】"]

    for day in weather[:5]:
        date = _as_str(day.get("date")) or "未知日期"
        high = _as_str(day.get("maxtempC"))
        low = _as_str(day.get("mintempC"))
        hourly = _as_list_of_dict(day.get("hourly"))
        midday = _pick_mid_hourly(day)
        weather_text = _extract_weather_text(midday)
        rain_chance = _extract_rain_chance(hourly)
        max_wind = _extract_max_wind_speed(hourly)

        day_info = [f"{date}:"]
        if weather_text:
            day_info.append(weather_text)
        if low and high:
            day_info.append(f"{low}~{high}°C")
        if rain_chance is not None and rain_chance > 0:
            day_info.append(f"降水概率{rain_chance}%")
        if max_wind is not None:
            day_info.append(f"风速{max_wind}km/h")

        msg.append(" ".join(day_info))

    return "\n".join(msg)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    location = args.get("location")
    query_type = args.get("query_type", "now")

    if not location:
        return "请提供城市名称。"

    try:
        if query_type == "forecast":
            return await get_weather_forecast(location, context)
        return await get_weather_now(location, context)
    except httpx.TimeoutException as e:
        logger.error(f"天气查询超时: {e}", exc_info=True)
        return _format_error(e)
    except httpx.HTTPStatusError as e:
        logger.error(f"天气查询 HTTP 错误: {e}", exc_info=True)
        return _format_error(e)
    except Exception as e:
        logger.exception(f"天气查询工具出错: {e}")
        return _format_error(e)
