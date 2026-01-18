from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """给指定QQ号点赞

    参数:
        args: 工具参数，包含 target_user_id 和可选的 times
        context: 工具上下文，包含 send_like_callback 等回调函数

    返回:
        操作结果描述
    """
    target_user_id = args.get("target_user_id")
    times = args.get("times", 1)

    if target_user_id is None:
        return "请提供要点赞的目标QQ号（target_user_id参数）"

    # 验证参数类型
    try:
        target_user_id = int(target_user_id)
        times = int(times)
    except (ValueError, TypeError):
        return "参数类型错误：target_user_id和times必须是整数"

    if times < 1:
        return "点赞次数必须大于0"
    if times > 10:  # 限制最大点赞次数，避免滥用
        return "单次点赞次数不能超过10次"

    send_like_callback = context.get("send_like_callback")
    if not send_like_callback:
        return "点赞功能不可用（回调函数未设置）"

    try:
        # 调用点赞回调
        await send_like_callback(target_user_id, times)

        if times == 1:
            return f"✅ 已给 QQ{target_user_id} 点赞。"
        else:
            return f"✅ 已给 QQ{target_user_id} 点赞 {times} 次。"

    except Exception as e:
        logger.exception(f"点赞失败: {e}")
        error_msg = str(e)

        # 根据错误消息提供更友好的提示
        if "SVIP 上限" in error_msg:
            return "点赞失败：今日给同一好友的点赞数已达SVIP上限"
        elif "点赞失败" in error_msg:
            return f"点赞失败：{error_msg}"
        else:
            return f"点赞失败：{error_msg}"
