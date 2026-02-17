import json
from typing import Any, Dict, Optional
from datetime import datetime


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取当前系统时间，支持公历、农历、黄历等多种信息"""
    format_type = args.get("format", "iso")
    include_lunar = args.get("include_lunar", False)
    include_almanac = args.get("include_almanac", False)

    now = datetime.now().astimezone()

    # 默认行为：返回 ISO 8601 格式（向后兼容）
    if format_type == "iso":
        return now.isoformat(timespec="seconds")

    # 需要农历/黄历时才导入库
    lunar_obj = None
    solar_obj = None
    if include_lunar or include_almanac:
        try:
            from lunar_python import Solar

            solar_obj = Solar.fromDate(now)
            lunar_obj = solar_obj.getLunar()
        except ImportError:
            # 如果库不可用，降级到基础功能
            pass

    if format_type == "text":
        return _format_text(now, lunar_obj, solar_obj, include_lunar, include_almanac)
    elif format_type == "json":
        return json.dumps(
            _format_json(now, lunar_obj, solar_obj, include_lunar, include_almanac),
            ensure_ascii=False,
            indent=2,
        )

    # 默认返回 ISO 格式
    return now.isoformat(timespec="seconds")


def _format_text(
    now: datetime,
    lunar: Optional[Any],
    solar: Optional[Any],
    include_lunar: bool,
    include_almanac: bool,
) -> str:
    """生成人类可读的文本格式"""
    lines = []

    # 公历信息
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday = weekdays[now.weekday()]
    tz_offset = now.strftime("%z")
    tz_str = f"UTC{tz_offset[:3]}:{tz_offset[3:]}" if tz_offset else "UTC"

    lines.append(
        f"公历：{now.year}年{now.month}月{now.day}日 {weekday} "
        f"{now.hour:02d}:{now.minute:02d}:{now.second:02d} ({tz_str})"
    )

    # 农历信息
    if include_lunar and lunar:
        year_gz = lunar.getYearInGanZhi()
        zodiac = lunar.getYearShengXiao()
        month_cn = lunar.getMonthInChinese()
        day_cn = lunar.getDayInChinese()
        lines.append(f"农历：{year_gz}年({zodiac}年) {month_cn}{day_cn}")

        # 干支信息
        month_gz = lunar.getMonthInGanZhi()
        day_gz = lunar.getDayInGanZhi()
        lines.append(f"干支：{year_gz}年 {month_gz}月 {day_gz}日")

    # 黄历信息
    if include_almanac and lunar:
        # 节气
        jieqi = lunar.getCurrentJieQi()
        if jieqi:
            lines.append(f"节气：{jieqi.getName()}")

        # 节日
        festivals = []
        if solar:
            solar_festivals = solar.getFestivals()
            festivals.extend(solar_festivals)
        lunar_festivals = lunar.getFestivals()
        festivals.extend(lunar_festivals)
        if festivals:
            lines.append(f"节日：{' '.join(festivals)}")

        # 宜忌
        yi = lunar.getDayYi()
        if yi:
            lines.append(f"宜：{' '.join(yi)}")
        ji = lunar.getDayJi()
        if ji:
            lines.append(f"忌：{' '.join(ji)}")

        # 冲煞
        chong = lunar.getDayChongDesc()
        sha = lunar.getDaySha()
        if chong or sha:
            chong_sha = f"冲{chong}" if chong else ""
            if sha:
                chong_sha += f"煞{sha}"
            lines.append(f"冲煞：{chong_sha}")

        # 胎神
        tai = lunar.getDayPositionTai()
        if tai:
            lines.append(f"胎神：{tai}")

    return "\n".join(lines)


def _format_json(
    now: datetime,
    lunar: Optional[Any],
    solar: Optional[Any],
    include_lunar: bool,
    include_almanac: bool,
) -> Dict[str, Any]:
    """生成结构化 JSON 格式"""
    result: Dict[str, Any] = {}

    # 公历信息
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday = weekdays[now.weekday()]
    tz_offset = now.strftime("%z")
    tz_str = f"UTC{tz_offset[:3]}:{tz_offset[3:]}" if tz_offset else "UTC"

    result["solar"] = {
        "datetime": now.isoformat(timespec="seconds"),
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "hour": now.hour,
        "minute": now.minute,
        "second": now.second,
        "weekday": weekday,
        "timezone": tz_str,
    }

    # 农历信息
    if include_lunar and lunar:
        result["lunar"] = {
            "year_cn": lunar.getYearInGanZhi(),
            "month_cn": lunar.getMonthInChinese(),
            "day_cn": lunar.getDayInChinese(),
            "zodiac": lunar.getYearShengXiao(),
            "ganzhi": {
                "year": lunar.getYearInGanZhi(),
                "month": lunar.getMonthInGanZhi(),
                "day": lunar.getDayInGanZhi(),
            },
        }

    # 黄历信息
    if include_almanac and lunar:
        almanac: Dict[str, Any] = {}

        # 节气
        jieqi = lunar.getCurrentJieQi()
        if jieqi:
            almanac["solar_term"] = {"current": jieqi.getName()}

        # 节日
        festivals = []
        if solar:
            solar_festivals = solar.getFestivals()
            festivals.extend(solar_festivals)
        lunar_festivals = lunar.getFestivals()
        festivals.extend(lunar_festivals)
        if festivals:
            almanac["festivals"] = festivals

        # 宜忌
        yi = lunar.getDayYi()
        if yi:
            almanac["yi"] = yi
        ji = lunar.getDayJi()
        if ji:
            almanac["ji"] = ji

        # 冲煞
        chong = lunar.getDayChongDesc()
        sha = lunar.getDaySha()
        if chong or sha:
            chong_sha = f"冲{chong}" if chong else ""
            if sha:
                chong_sha += f"煞{sha}"
            almanac["chong"] = chong_sha

        # 胎神
        tai = lunar.getDayPositionTai()
        if tai:
            almanac["fetal_god"] = tai

        result["almanac"] = almanac

    return result
