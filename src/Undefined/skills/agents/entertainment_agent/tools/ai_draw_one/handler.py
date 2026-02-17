from typing import Any, Dict
import logging
import uuid

from Undefined.skills.http_client import request_with_retry
from Undefined.skills.http_config import get_request_timeout, get_xingzhige_url

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    prompt = args.get("prompt")
    # model 参数暂时不使用
    size = args.get("size", "1:1")
    target_id = args.get("target_id")
    message_type = args.get("message_type")

    url = get_xingzhige_url("/API/DrawOne/")
    # params = {"prompt": prompt, "model": model, "size": size}
    params = {"prompt": prompt, "size": size}

    try:
        timeout = get_request_timeout(60.0)
        response = await request_with_retry(
            "GET",
            url,
            params=params,
            timeout=timeout,
            context=context,
        )

        try:
            data = response.json()
        except Exception:
            return f"API 返回错误 (非JSON): {response.text[:100]}"

        try:
            image_url = data["data"][0]["url"]
            logger.info(f"API 返回原文: {data}")
            logger.info(f"提取到的图片链接: {image_url}")
        except (KeyError, IndexError):
            logger.error(f"API 返回原文 (错误：未找到图片链接): {data}")
            return f"API 返回原文 (错误：未找到图片链接): {data}"

        # 下载图片
        img_response = await request_with_retry(
            "GET",
            str(image_url),
            timeout=max(timeout, 15.0),
            context=context,
        )

        filename = f"ai_draw_{uuid.uuid4().hex[:8]}.jpg"
        from Undefined.utils.paths import IMAGE_CACHE_DIR, ensure_dir

        filepath = ensure_dir(IMAGE_CACHE_DIR) / filename

        with open(filepath, "wb") as f:
            f.write(img_response.content)

        send_image_callback = context.get("send_image_callback")
        if send_image_callback:
            await send_image_callback(target_id, message_type, str(filepath))
            return f"AI 绘图已发送给 {message_type} {target_id}"
        return "发送图片回调未设置"

    except Exception as e:
        logger.exception(f"AI 绘图失败: {e}")
        return "AI 绘图失败，请稍后重试"
