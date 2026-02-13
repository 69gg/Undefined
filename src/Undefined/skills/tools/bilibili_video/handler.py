from typing import Any, Dict, Literal
import logging

from Undefined.bilibili.sender import send_bilibili_video

logger = logging.getLogger(__name__)


def _resolve_target(
    args: Dict[str, Any], context: Dict[str, Any]
) -> tuple[tuple[Literal["group", "private"], int] | None, str | None]:
    """解析目标会话，复用 send_message 的逻辑模式。"""
    target_type_raw = args.get("target_type")
    target_id_raw = args.get("target_id")

    if target_type_raw is not None and target_id_raw is not None:
        target_type = str(target_type_raw).strip().lower()
        if target_type not in ("group", "private"):
            return None, "target_type 只能是 group 或 private"
        try:
            target_id = int(target_id_raw)
        except (TypeError, ValueError):
            return None, "target_id 必须是整数"
        return (target_type, target_id), None  # type: ignore[return-value]

    # 从上下文推断
    request_type = context.get("request_type")
    if request_type == "group":
        group_id = context.get("group_id")
        if group_id:
            return ("group", int(group_id)), None
    elif request_type == "private":
        user_id = context.get("user_id")
        if user_id:
            return ("private", int(user_id)), None

    # 兜底
    group_id = context.get("group_id")
    if group_id:
        return ("group", int(group_id)), None
    user_id = context.get("user_id")
    if user_id:
        return ("private", int(user_id)), None

    return None, "无法确定目标会话，请提供 target_type 与 target_id"


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """下载并发送 Bilibili 视频"""
    video_id = args.get("video_id", "")
    if not video_id:
        return "video_id 不能为空"

    # 解析目标
    target, error = _resolve_target(args, context)
    if error or target is None:
        return f"目标解析失败: {error or '参数错误'}"
    target_type, target_id = target

    # 获取配置
    runtime_config = context.get("runtime_config")
    sender = context.get("sender")
    onebot = context.get("onebot")

    if not sender or not onebot:
        return "缺少必要的运行时组件（sender/onebot）"

    # 读取 bilibili 配置
    cookie = ""
    prefer_quality = 80
    max_duration = 600
    max_file_size = 100
    oversize_strategy = "downgrade"

    if runtime_config:
        cookie = getattr(
            runtime_config,
            "bilibili_cookie",
            getattr(runtime_config, "bilibili_sessdata", ""),
        )
        prefer_quality = getattr(runtime_config, "bilibili_prefer_quality", 80)
        max_duration = getattr(runtime_config, "bilibili_max_duration", 600)
        max_file_size = getattr(runtime_config, "bilibili_max_file_size", 100)
        oversize_strategy = getattr(
            runtime_config, "bilibili_oversize_strategy", "downgrade"
        )

    try:
        result = await send_bilibili_video(
            video_id=video_id,
            sender=sender,
            onebot=onebot,
            target_type=target_type,
            target_id=target_id,
            cookie=cookie,
            prefer_quality=prefer_quality,
            max_duration=max_duration,
            max_file_size=max_file_size,
            oversize_strategy=oversize_strategy,
        )
        return result
    except Exception as exc:
        logger.exception("[bilibili_video] 执行失败: %s", exc)
        return f"视频处理失败: {exc}"
