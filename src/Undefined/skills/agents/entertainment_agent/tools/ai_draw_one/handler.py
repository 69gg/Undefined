"""AI 绘图工具 handler

支持两种生图 provider：
- xingzhige: 调用免费星之阁 API (GET /API/DrawOne/)
- models: 调用 OpenAI 兼容的图片生成接口 (POST /v1/images/generations)
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from Undefined.skills.http_client import request_with_retry
from Undefined.skills.http_config import get_request_timeout, get_xingzhige_url

logger = logging.getLogger(__name__)


def _record_image_gen_usage(
    model_name: str, prompt: str, duration_seconds: float, success: bool
) -> None:
    """记录生图调用统计（静默失败，不影响主流程）"""
    try:
        import asyncio

        from Undefined.token_usage_storage import TokenUsage, TokenUsageStorage

        storage = TokenUsageStorage()
        usage = TokenUsage(
            timestamp=_iso_now(),
            model_name=model_name,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            duration_seconds=duration_seconds,
            call_type="image_gen",
            success=success,
        )
        asyncio.create_task(storage.record(usage))
    except Exception:
        pass


def _iso_now() -> str:
    from datetime import datetime

    return datetime.now().isoformat()


def _parse_image_url(data: dict[str, Any]) -> str | None:
    """从 API 响应中提取图片 URL"""
    try:
        return str(data["data"][0]["url"])
    except (KeyError, IndexError, TypeError):
        return None


async def _call_xingzhige(prompt: str, size: str, context: dict[str, Any]) -> str:
    """调用星之阁免费 API"""
    url = get_xingzhige_url("/API/DrawOne/")
    params: dict[str, Any] = {"prompt": prompt, "size": size}
    timeout = get_request_timeout(60.0)

    response = await request_with_retry(
        "GET",
        url,
        params=params,
        timeout=timeout,
        context=context,
    )

    try:
        data: dict[str, Any] = response.json()
    except Exception:
        return f"API 返回错误 (非JSON): {response.text[:100]}"

    image_url = _parse_image_url(data)
    if image_url is None:
        logger.error(f"星之阁 API 返回 (未找到图片链接): {data}")
        return f"API 返回原文 (错误：未找到图片链接): {data}"

    logger.info(f"星之阁 API 返回: {data}")
    logger.info(f"提取图片链接: {image_url}")
    return image_url


async def _call_openai_models(
    prompt: str,
    api_url: str,
    api_key: str,
    model_name: str,
    size: str,
    quality: str,
    style: str,
    timeout_val: float,
    context: dict[str, Any],
) -> str:
    """调用 OpenAI 兼容的图片生成接口"""
    from Undefined.utils.request_params import merge_request_params

    # 构建请求 body（仅包含非空字段，其余由上游使用默认值）
    body: dict[str, Any] = {
        "prompt": prompt,
        "n": 1,
    }
    if model_name:
        body["model"] = model_name
    if size:
        body["size"] = size
    if quality:
        body["quality"] = quality
    if style:
        body["style"] = style

    # 追加 request_params
    try:
        from Undefined.config import get_config

        extra_params = get_config(strict=False).models_image_gen.request_params
        body = merge_request_params(body, extra_params)
    except Exception:
        pass

    # 确保 base_url 末尾带 /v1
    base_url = api_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    url = f"{base_url}/images/generations"

    headers: dict[str, str] = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    response = await request_with_retry(
        "POST",
        url,
        json_data=body,
        headers=headers,
        timeout=timeout_val,
        context=context,
    )

    try:
        data = response.json()
    except Exception:
        return f"API 返回错误 (非JSON): {response.text[:100]}"

    image_url = _parse_image_url(data)
    if image_url is None:
        logger.error(f"图片生成 API 返回 (未找到图片链接): {data}")
        return f"API 返回原文 (错误：未找到图片链接): {data}"

    logger.info(f"图片生成 API 返回: {data}")
    logger.info(f"提取图片链接: {image_url}")
    return image_url


async def _download_and_send(
    image_url: str,
    target_id: int | str,
    message_type: str,
    timeout_val: float,
    context: dict[str, Any],
) -> str:
    """下载图片并发送"""
    img_response = await request_with_retry(
        "GET",
        str(image_url),
        timeout=max(timeout_val, 15.0),
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


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """执行 AI 绘图"""
    from Undefined.config import get_config

    prompt_arg: str | None = args.get("prompt")
    size_arg: str | None = args.get("size")
    target_id: int | str | None = args.get("target_id")
    message_type_arg: str | None = args.get("message_type")

    cfg = get_config(strict=False).image_gen
    gen_cfg = get_config(strict=False).models_image_gen
    chat_cfg = get_config(strict=False).chat_model
    provider = cfg.provider

    start_time = time.time()
    success = False
    used_model = provider

    try:
        if provider == "xingzhige":
            prompt = prompt_arg or ""
            size = size_arg or cfg.xingzhige_size
            image_url = await _call_xingzhige(prompt, size, context)
        elif provider == "models":
            prompt = prompt_arg or ""
            # 降级到 models.image_gen 配置，未填则降级到 chat_model
            api_url = gen_cfg.api_url or chat_cfg.api_url
            api_key = gen_cfg.api_key or chat_cfg.api_key
            model_name = gen_cfg.model_name
            size = size_arg or cfg.openai_size
            quality = cfg.openai_quality
            style = cfg.openai_style
            timeout_val = cfg.openai_timeout

            if not api_url:
                return "图片生成失败：未配置 models.image_gen.api_url"
            if not api_key:
                return "图片生成失败：未配置 models.image_gen.api_key"

            used_model = model_name or "openai-image-gen"
            image_url = await _call_openai_models(
                prompt=prompt,
                api_url=api_url,
                api_key=api_key,
                model_name=model_name,
                size=size,
                quality=quality,
                style=style,
                timeout_val=timeout_val,
                context=context,
            )
        else:
            return (
                f"未知的生图 provider: {provider}，"
                "请在 config.toml 中设置 image_gen.provider 为 xingzhige 或 models"
            )

        # 判断是否返回了错误消息（而非图片 URL）
        if not image_url.startswith("http"):
            return image_url

        if target_id is None or message_type_arg is None:
            return "图片生成成功，但缺少发送目标参数"

        send_timeout = get_request_timeout(60.0)
        result = await _download_and_send(
            image_url, target_id, message_type_arg, send_timeout, context
        )
        success = True
        return result

    except Exception as e:
        logger.exception(f"AI 绘图失败: {e}")
        return "AI 绘图失败，请稍后重试"
    finally:
        duration = time.time() - start_time
        if provider == "models":
            _record_image_gen_usage(used_model, prompt_arg or "", duration, success)
