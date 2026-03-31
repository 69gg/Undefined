"""AI 绘图工具 handler

支持两种生图 provider：
- xingzhige: 调用免费星之阁 API (GET /API/DrawOne/)
- models: 调用 OpenAI 兼容的图片生成接口 (POST /v1/images/generations)
"""

from __future__ import annotations

import base64
import binascii
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from Undefined.skills.http_client import request_with_retry
from Undefined.skills.http_config import get_request_timeout, get_xingzhige_url

logger = logging.getLogger(__name__)

_ALLOWED_MODELS_IMAGE_SIZES = (
    "1280x720",
    "720x1280",
    "1792x1024",
    "1024x1792",
    "1024x1024",
)
_ALLOWED_IMAGE_RESPONSE_FORMATS = ("url", "b64_json", "base64")


@dataclass
class _GeneratedImagePayload:
    image_url: str | None = None
    image_bytes: bytes | None = None


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


def _parse_image_bytes(data: dict[str, Any]) -> bytes | None:
    """从 API 响应中提取 Base64 图片内容。"""
    try:
        image_item = data["data"][0]
    except (KeyError, IndexError, TypeError):
        return None

    if not isinstance(image_item, dict):
        return None

    for key in ("b64_json", "base64"):
        raw_value = image_item.get(key)
        if raw_value is None:
            continue
        text = str(raw_value).strip()
        if not text:
            continue
        try:
            return base64.b64decode(text)
        except (binascii.Error, ValueError):
            logger.error("图片 Base64 解码失败: key=%s", key)
            return None
    return None


def _parse_generated_image(data: dict[str, Any]) -> _GeneratedImagePayload | None:
    image_url = _parse_image_url(data)
    if image_url:
        return _GeneratedImagePayload(image_url=image_url)

    image_bytes = _parse_image_bytes(data)
    if image_bytes is not None:
        return _GeneratedImagePayload(image_bytes=image_bytes)

    return None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _build_openai_models_request_body(
    *,
    prompt: str,
    model_name: str,
    size: str,
    quality: str,
    style: str,
    response_format: str,
    n: int | None,
    extra_params: dict[str, Any],
) -> dict[str, Any]:
    from Undefined.utils.request_params import merge_request_params

    body = merge_request_params(extra_params)
    body["prompt"] = prompt
    if n is not None:
        body["n"] = n
    else:
        body.setdefault("n", 1)
    if model_name:
        body["model"] = model_name
    if size:
        body["size"] = size
    if quality:
        body["quality"] = quality
    if style:
        body["style"] = style
    if response_format:
        body["response_format"] = response_format
    return body


def _validate_openai_models_request_body(body: dict[str, Any]) -> str | None:
    size = str(body.get("size", "") or "").strip()
    if size and size not in _ALLOWED_MODELS_IMAGE_SIZES:
        supported = ", ".join(_ALLOWED_MODELS_IMAGE_SIZES)
        return f"size 无效：{size}。models provider 仅支持: {supported}"

    response_format = str(body.get("response_format", "") or "").strip()
    if response_format and response_format not in _ALLOWED_IMAGE_RESPONSE_FORMATS:
        supported = ", ".join(_ALLOWED_IMAGE_RESPONSE_FORMATS)
        return f"response_format 无效：{response_format}。仅支持: {supported}"

    raw_n = body.get("n", 1)
    try:
        n = int(raw_n)
    except (TypeError, ValueError):
        return f"n 无效：{raw_n}。必须是 1 到 10 的整数"

    if not 1 <= n <= 10:
        return f"n 无效：{n}。必须是 1 到 10 的整数"

    if _coerce_bool(body.get("stream")):
        if n not in {1, 2}:
            return "stream=true 时 n 只能是 1 或 2"
        return "暂不支持 stream=true 的绘图响应"

    return None


def _detect_image_suffix(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if image_bytes.startswith(b"BM"):
        return ".bmp"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return ".webp"
    return ".png"


def _write_image_cache_file(image_bytes: bytes) -> str:
    from Undefined.utils.paths import IMAGE_CACHE_DIR, ensure_dir

    suffix = _detect_image_suffix(image_bytes)
    filename = f"ai_draw_{uuid.uuid4().hex[:8]}{suffix}"
    filepath = ensure_dir(IMAGE_CACHE_DIR) / filename
    with open(filepath, "wb") as f:
        f.write(image_bytes)
    return str(filepath)


async def _send_cached_image(
    filepath: str,
    target_id: int | str,
    message_type: str,
    context: dict[str, Any],
) -> str:
    send_image_callback = context.get("send_image_callback")
    if send_image_callback:
        await send_image_callback(target_id, message_type, filepath)
        return f"AI 绘图已发送给 {message_type} {target_id}"
    return "发送图片回调未设置"


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
    response_format: str,
    n: int | None,
    timeout_val: float,
    context: dict[str, Any],
) -> _GeneratedImagePayload | str:
    """调用 OpenAI 兼容的图片生成接口"""

    # 追加 request_params
    extra_params: dict[str, Any] = {}
    try:
        from Undefined.config import get_config

        extra_params = get_config(strict=False).models_image_gen.request_params
    except Exception:
        extra_params = {}

    body = _build_openai_models_request_body(
        prompt=prompt,
        model_name=model_name,
        size=size,
        quality=quality,
        style=style,
        response_format=response_format,
        n=n,
        extra_params=extra_params,
    )

    validation_error = _validate_openai_models_request_body(body)
    if validation_error:
        return validation_error

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

    generated_image = _parse_generated_image(data)
    if generated_image is None:
        logger.error(f"图片生成 API 返回 (未找到图片链接): {data}")
        return f"API 返回原文 (错误：未找到图片内容): {data}"

    logger.info(f"图片生成 API 返回: {data}")
    if generated_image.image_url:
        logger.info(f"提取图片链接: {generated_image.image_url}")
    elif generated_image.image_bytes is not None:
        logger.info("提取图片字节: bytes=%s", len(generated_image.image_bytes))
    return generated_image


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
    filepath = _write_image_cache_file(img_response.content)
    return await _send_cached_image(filepath, target_id, message_type, context)


async def _save_and_send(
    image_bytes: bytes,
    target_id: int | str,
    message_type: str,
    context: dict[str, Any],
) -> str:
    filepath = _write_image_cache_file(image_bytes)
    return await _send_cached_image(filepath, target_id, message_type, context)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """执行 AI 绘图"""
    from Undefined.config import get_config

    prompt_arg: str | None = args.get("prompt")
    size_arg: str | None = args.get("size")
    model_arg: str | None = args.get("model")
    quality_arg: str | None = args.get("quality")
    style_arg: str | None = args.get("style")
    response_format_arg: str | None = args.get("response_format")
    n_arg = args.get("n")
    target_id: int | str | None = args.get("target_id")
    message_type_arg: str | None = args.get("message_type")

    cfg = get_config(strict=False).image_gen
    gen_cfg = get_config(strict=False).models_image_gen
    chat_cfg = get_config(strict=False).chat_model
    provider = cfg.provider

    start_time = time.time()
    success = False
    used_model = provider
    generated_result: str | _GeneratedImagePayload

    try:
        if provider == "xingzhige":
            prompt = prompt_arg or ""
            size = size_arg or cfg.xingzhige_size
            generated_result = await _call_xingzhige(prompt, size, context)
        elif provider == "models":
            prompt = prompt_arg or ""
            # 降级到 models.image_gen 配置，未填则降级到 chat_model
            api_url = gen_cfg.api_url or chat_cfg.api_url
            api_key = gen_cfg.api_key or chat_cfg.api_key
            model_name = str(model_arg or gen_cfg.model_name or "").strip()
            size = str(size_arg or cfg.openai_size or "").strip()
            quality = str(quality_arg or cfg.openai_quality or "").strip()
            style = str(style_arg or cfg.openai_style or "").strip()
            response_format = str(response_format_arg or "").strip()
            timeout_val = cfg.openai_timeout
            n_value: int | None = None
            if n_arg is not None and str(n_arg).strip() != "":
                try:
                    n_value = int(n_arg)
                except (TypeError, ValueError):
                    return f"n 无效：{n_arg}。必须是 1 到 10 的整数"

            if not api_url:
                return "图片生成失败：未配置 models.image_gen.api_url"
            if not api_key:
                return "图片生成失败：未配置 models.image_gen.api_key"

            used_model = model_name or "openai-image-gen"
            generated_result = await _call_openai_models(
                prompt=prompt,
                api_url=api_url,
                api_key=api_key,
                model_name=model_name,
                size=size,
                quality=quality,
                style=style,
                response_format=response_format,
                n=n_value,
                timeout_val=timeout_val,
                context=context,
            )
        else:
            return (
                f"未知的生图 provider: {provider}，"
                "请在 config.toml 中设置 image_gen.provider 为 xingzhige 或 models"
            )

        if isinstance(generated_result, _GeneratedImagePayload):
            generated_image = generated_result
        else:
            if not generated_result.startswith("http"):
                return generated_result
            generated_image = _GeneratedImagePayload(image_url=generated_result)

        if target_id is None or message_type_arg is None:
            return "图片生成成功，但缺少发送目标参数"

        send_timeout = get_request_timeout(60.0)
        if generated_image.image_url:
            result = await _download_and_send(
                generated_image.image_url,
                target_id,
                message_type_arg,
                send_timeout,
                context,
            )
        elif generated_image.image_bytes is not None:
            result = await _save_and_send(
                generated_image.image_bytes, target_id, message_type_arg, context
            )
        else:
            return "图片生成失败：未找到可发送的图片内容"
        success = True
        return result

    except Exception as e:
        logger.exception(f"AI 绘图失败: {e}")
        return "AI 绘图失败，请稍后重试"
    finally:
        duration = time.time() - start_time
        if provider == "models":
            _record_image_gen_usage(used_model, prompt_arg or "", duration, success)
