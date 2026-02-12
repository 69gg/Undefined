"""时间解析工具函数"""

from datetime import datetime


def parse_time_range(
    start_time: str | None, end_time: str | None
) -> tuple[datetime | None, datetime | None]:
    """解析时间范围，返回 datetime 对象

    参数:
        start_time: 开始时间字符串，格式：YYYY-MM-DD HH:MM:SS
        end_time: 结束时间字符串，格式：YYYY-MM-DD HH:MM:SS

    返回:
        (start_dt, end_dt) 元组，如果解析失败则对应位置为 None
    """
    start_dt: datetime | None = None
    end_dt: datetime | None = None

    if start_time:
        try:
            start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    if end_time:
        try:
            end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    return start_dt, end_dt


def format_datetime(dt: datetime | None) -> str:
    """格式化 datetime 对象为字符串

    参数:
        dt: datetime 对象

    返回:
        格式化的时间字符串，格式：YYYY-MM-DD HH:MM:SS
    """
    if dt is None:
        return "未指定"
    return dt.strftime("%Y-%m-%d %H:%M:%S")
