"""AI 绘图工具 handler

支持两种生图 provider：
- xingzhige: 调用免费星之阁 API (GET /API/DrawOne/)
- models: 调用 OpenAI 兼容的图片生成接口 (POST /v1/images/generations)
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import mimetypes
from pathlib import Path
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from Undefined.attachments import scope_from_context
from Undefined.ai.parsing import extract_choices_content
from Undefined.skills.http_client import request_with_retry
from Undefined.skills.http_config import get_request_timeout, get_xingzhige_url
from Undefined.utils.resources import read_text_resource

logger = logging.getLogger(__name__)

_ALLOWED_MODELS_IMAGE_SIZES = (
    "1280x720",
    "720x1280",
    "1792x1024",
    "1024x1792",
    "1024x1024",
)
_ALLOWED_IMAGE_RESPONSE_FORMATS = ("url", "b64_json", "base64")
_MAX_REFERENCE_IMAGE_UIDS = 16
_IMAGE_GEN_MODERATION_PROMPT: str | None = None


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


def _format_upstream_error_message(response: httpx.Response) -> str:
    default_message = response.text[:200] or f"HTTP {response.status_code}"
    try:
        data = response.json()
    except Exception:
        return default_message

    if not isinstance(data, dict):
        return default_message

    error = data.get("error")
    if isinstance(error, dict):
        code = str(error.get("code", "") or "").strip()
        message = str(error.get("message", "") or "").strip()
        if code and message:
            return f"{code}: {message}"
        if message:
            return message
        if code:
            return code

    message = str(data.get("message", "") or "").strip()
    return message or default_message


def _get_image_gen_moderation_prompt() -> str:
    global _IMAGE_GEN_MODERATION_PROMPT
    if _IMAGE_GEN_MODERATION_PROMPT is not None:
        return _IMAGE_GEN_MODERATION_PROMPT
    try:
        _IMAGE_GEN_MODERATION_PROMPT = read_text_resource(
            "res/prompts/image_gen_moderation.txt"
        )
    except Exception as exc:
        logger.error("加载生图审核提示词失败: %s", exc)
        _IMAGE_GEN_MODERATION_PROMPT = (
            "你是图片生成审核助手。"
            "你只根据待生成图片的提示词判断是否允许生成。"
            "如果安全则只输出 ALLOW。"
            "如果应拒绝则输出 BLOCK: <简短中文原因>。"
        )
    return _IMAGE_GEN_MODERATION_PROMPT


def _resolve_agent_model_for_moderation(context: dict[str, Any]) -> Any | None:
    ai_client = context.get("ai_client")
    if ai_client is None:
        return None
    model_config = getattr(ai_client, "agent_config", None)
    if model_config is None:
        return None

    runtime_config = context.get("runtime_config")
    model_selector = getattr(ai_client, "model_selector", None)
    if runtime_config is not None and model_selector is not None:
        try:
            group_id = context.get("group_id", 0) or 0
            user_id = context.get("user_id", 0) or 0
            global_enabled = bool(getattr(runtime_config, "model_pool_enabled", False))
            selected = model_selector.select_agent_config(
                model_config,
                group_id=group_id,
                user_id=user_id,
                global_enabled=global_enabled,
            )
            if selected is not None:
                return selected
        except Exception as exc:
            logger.debug("生图审核选择 agent 模型失败，回退默认 agent_config: %s", exc)
    return model_config


async def _moderate_prompt_with_agent_model(
    prompt: str,
    context: dict[str, Any],
) -> str | None:
    text = str(prompt or "").strip()
    if not text:
        return None

    ai_client = context.get("ai_client")
    model_config = _resolve_agent_model_for_moderation(context)
    if ai_client is None or model_config is None:
        logger.debug("生图审核跳过：缺少 ai_client 或 agent 模型配置")
        return None

    try:
        result = await ai_client.request_model(
            model_config=model_config,
            messages=[
                {"role": "system", "content": _get_image_gen_moderation_prompt()},
                {"role": "user", "content": f"待审核的生图提示词：\n{text}"},
            ],
            max_tokens=64,
            call_type="image_gen_moderation",
        )
        content = extract_choices_content(result).strip()
    except Exception as exc:
        logger.warning("生图审核调用失败，按允许继续: %s", exc)
        return None

    upper = content.upper()
    if upper.startswith("ALLOW"):
        return None
    if upper.startswith("BLOCK"):
        reason = content.split(":", 1)[1].strip() if ":" in content else "命中敏感内容"
        return f"图片生成请求被审核拦截：{reason or '命中敏感内容'}"

    logger.warning("生图审核返回了无法识别的结果，按允许继续: %s", content)
    return None


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
    else:
        body.setdefault("response_format", "base64")
    return body


def _coerce_reference_image_uids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    resolved: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        resolved.append(text)
    return resolved


def _stringify_multipart_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def _build_openai_models_edit_form(
    *,
    prompt: str,
    model_name: str,
    size: str,
    quality: str,
    style: str,
    response_format: str,
    n: int | None,
    extra_params: dict[str, Any],
) -> dict[str, str]:
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
    else:
        body.setdefault("response_format", "base64")
    return {key: _stringify_multipart_value(value) for key, value in body.items()}


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

    try:
        response = await request_with_retry(
            "POST",
            url,
            json_data=body,
            headers=headers,
            timeout=timeout_val,
            context=context,
        )
    except httpx.HTTPStatusError as exc:
        message = _format_upstream_error_message(exc.response)
        return f"图片生成请求失败: HTTP {exc.response.status_code} {message}"
    except httpx.TimeoutException:
        return f"图片生成请求超时（{timeout_val:.0f}s）"
    except httpx.RequestError as exc:
        return f"图片生成请求失败: {exc}"

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


def _guess_upload_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return str(guessed or "application/octet-stream")


async def _resolve_reference_image_paths(
    reference_image_uids: list[str],
    context: dict[str, Any],
) -> tuple[list[Path] | None, str | None]:
    if not reference_image_uids:
        return [], None
    if len(reference_image_uids) > _MAX_REFERENCE_IMAGE_UIDS:
        return (
            None,
            f"reference_image_uids 最多支持 {_MAX_REFERENCE_IMAGE_UIDS} 张参考图",
        )

    attachment_registry = context.get("attachment_registry")
    scope_key = scope_from_context(context)
    if attachment_registry is None or not scope_key:
        return None, "当前会话未提供附件注册能力，无法解析参考图 UID"

    resolved_paths: list[Path] = []
    for uid in reference_image_uids:
        record = attachment_registry.resolve(uid, scope_key)
        if record is None:
            return None, f"参考图 UID 不存在或不属于当前会话：{uid}"
        if str(getattr(record, "media_type", "") or "").strip().lower() != "image":
            return None, f"参考图 UID 不是图片：{uid}"
        local_path = str(getattr(record, "local_path", "") or "").strip()
        if not local_path:
            return None, f"参考图 UID 缺少本地缓存文件：{uid}"
        path = Path(local_path)
        if not path.is_file():
            return None, f"参考图 UID 的本地缓存文件不存在：{uid}"
        resolved_paths.append(path)
    return resolved_paths, None


async def _call_openai_models_edit(
    *,
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
    reference_image_paths: list[Path],
    extra_params: dict[str, Any],
    context: dict[str, Any],
) -> _GeneratedImagePayload | str:
    form_data = _build_openai_models_edit_form(
        prompt=prompt,
        model_name=model_name,
        size=size,
        quality=quality,
        style=style,
        response_format=response_format,
        n=n,
        extra_params=extra_params,
    )
    validation_error = _validate_openai_models_request_body(
        {key: value for key, value in form_data.items()}
    )
    if validation_error:
        return validation_error

    base_url = api_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    url = f"{base_url}/images/edits"

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    file_handles: list[Any] = []
    files: list[tuple[str, tuple[str, Any, str]]] = []
    try:
        for path in reference_image_paths:
            file_handle = path.open("rb")
            file_handles.append(file_handle)
            files.append(
                (
                    "image",
                    (
                        path.name,
                        file_handle,
                        _guess_upload_media_type(path),
                    ),
                )
            )

        try:
            response = await request_with_retry(
                "POST",
                url,
                data=form_data,
                files=files,
                headers=headers or None,
                timeout=timeout_val,
                context=context,
            )
        except httpx.HTTPStatusError as exc:
            message = _format_upstream_error_message(exc.response)
            return f"参考图生图请求失败: HTTP {exc.response.status_code} {message}"
        except httpx.TimeoutException:
            return f"参考图生图请求超时（{timeout_val:.0f}s）"
        except httpx.RequestError as exc:
            return f"参考图生图请求失败: {exc}"

        try:
            data = response.json()
        except Exception:
            return f"API 返回错误 (非JSON): {response.text[:100]}"

        generated_image = _parse_generated_image(data)
        if generated_image is None:
            logger.error(f"参考图生图 API 返回 (未找到图片内容): {data}")
            return f"API 返回原文 (错误：未找到图片内容): {data}"

        logger.info(f"参考图生图 API 返回: {data}")
        if generated_image.image_url:
            logger.info(f"提取图片链接: {generated_image.image_url}")
        elif generated_image.image_bytes is not None:
            logger.info("提取图片字节: bytes=%s", len(generated_image.image_bytes))
        return generated_image
    finally:
        for handle in file_handles:
            try:
                handle.close()
            except Exception:
                pass


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


def _resolve_send_target(
    target_id: int | str | None,
    message_type: str | None,
    context: dict[str, Any],
) -> tuple[int | str | None, str | None, str | None]:
    if target_id is not None and message_type is not None:
        return target_id, message_type, None

    request_type = str(context.get("request_type", "") or "").strip().lower()
    if request_type == "group":
        resolved_group_id = context.get("group_id")
        if resolved_group_id is not None:
            return resolved_group_id, "group", None
    if request_type == "private":
        resolved_user_id = context.get("user_id")
        if resolved_user_id is not None:
            return resolved_user_id, "private", None

    return None, None, "图片生成成功，但缺少发送目标参数"


async def _register_generated_image(
    generated_image: _GeneratedImagePayload,
    context: dict[str, Any],
) -> tuple[Any | None, str | None]:
    attachment_registry = context.get("attachment_registry")
    scope_key = scope_from_context(context)
    if attachment_registry is None or not scope_key:
        return None, "当前会话未提供附件注册能力，无法生成可嵌入图片 UID"

    display_name = f"ai_draw_{uuid.uuid4().hex[:8]}.png"
    if generated_image.image_bytes is not None:
        record = await attachment_registry.register_bytes(
            scope_key,
            generated_image.image_bytes,
            kind="image",
            display_name=display_name,
            source_kind="generated_image",
            source_ref="ai_draw_one",
        )
        return record, None

    if generated_image.image_url:
        record = await attachment_registry.register_remote_url(
            scope_key,
            generated_image.image_url,
            kind="image",
            display_name=display_name,
            source_kind="generated_image_url",
            source_ref=generated_image.image_url,
        )
        return record, None

    return None, "图片生成失败：未找到可保存的图片内容"


async def _send_registered_record(
    record: Any,
    target_id: int | str,
    message_type: str,
    context: dict[str, Any],
) -> str:
    local_path = str(getattr(record, "local_path", "") or "").strip()
    if not local_path:
        return "图片生成失败：已生成图片，但本地缓存不可用"
    return await _send_cached_image(local_path, target_id, message_type, context)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """执行 AI 绘图"""
    from Undefined.config import get_config

    prompt_arg: str | None = args.get("prompt")
    size_arg: str | None = args.get("size")
    quality_arg: str | None = args.get("quality")
    style_arg: str | None = args.get("style")
    response_format_arg: str | None = args.get("response_format")
    n_arg = args.get("n")
    reference_image_uids = _coerce_reference_image_uids(
        args.get("reference_image_uids")
    )
    delivery = str(args.get("delivery", "embed") or "embed").strip().lower()
    target_id: int | str | None = args.get("target_id")
    message_type_arg: str | None = args.get("message_type")

    cfg = get_config(strict=False).image_gen
    gen_cfg = get_config(strict=False).models_image_gen
    edit_cfg = get_config(strict=False).models_image_edit
    chat_cfg = get_config(strict=False).chat_model
    provider = cfg.provider

    start_time = time.time()
    success = False
    used_model = provider
    generated_result: str | _GeneratedImagePayload

    try:
        if delivery not in {"embed", "send"}:
            return f"delivery 无效：{delivery}。仅支持 embed 或 send"
        moderation_error = await _moderate_prompt_with_agent_model(
            prompt_arg or "",
            context,
        )
        if moderation_error:
            logger.warning("AI 绘图请求被 agent 审核拦截: prompt=%s", prompt_arg or "")
            return moderation_error

        if provider == "xingzhige":
            if reference_image_uids:
                return "图片生成失败：xingzhige provider 不支持参考图生图"
            prompt = prompt_arg or ""
            size = size_arg or cfg.xingzhige_size
            generated_result = await _call_xingzhige(prompt, size, context)
        elif provider == "models":
            prompt = prompt_arg or ""
            use_reference_images = bool(reference_image_uids)
            selected_cfg = edit_cfg if use_reference_images else gen_cfg
            fallback_cfg = gen_cfg if use_reference_images else None
            # 降级到独立的 image 配置，未填再降级到 chat_model
            api_url = (
                selected_cfg.api_url
                or (fallback_cfg.api_url if fallback_cfg is not None else "")
                or chat_cfg.api_url
            )
            api_key = (
                selected_cfg.api_key
                or (fallback_cfg.api_key if fallback_cfg is not None else "")
                or chat_cfg.api_key
            )
            model_name = str(
                selected_cfg.model_name
                or (fallback_cfg.model_name if fallback_cfg is not None else "")
                or ""
            ).strip()
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
                return (
                    "图片生成失败：未配置 models.image_edit.api_url"
                    if use_reference_images
                    else "图片生成失败：未配置 models.image_gen.api_url"
                )
            if not api_key:
                return (
                    "图片生成失败：未配置 models.image_edit.api_key"
                    if use_reference_images
                    else "图片生成失败：未配置 models.image_gen.api_key"
                )

            used_model = model_name or "openai-image-gen"
            if use_reference_images:
                from Undefined.utils.request_params import merge_request_params

                (
                    reference_image_paths,
                    reference_error,
                ) = await _resolve_reference_image_paths(reference_image_uids, context)
                if reference_error:
                    return reference_error
                generated_result = await _call_openai_models_edit(
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
                    reference_image_paths=reference_image_paths or [],
                    extra_params=merge_request_params(
                        gen_cfg.request_params,
                        edit_cfg.request_params,
                    ),
                    context=context,
                )
            else:
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

        registered_record, register_error = await _register_generated_image(
            generated_image,
            context,
        )
        if delivery == "embed":
            if register_error or registered_record is None:
                return register_error or "图片生成失败：无法创建内嵌图片 UID"
            success = True
            uid = str(getattr(registered_record, "uid", "") or "").strip()
            return f'已生成图片，可在回复中插入 <pic uid="{uid}"/>'

        resolved_target_id, resolved_message_type, target_error = _resolve_send_target(
            target_id,
            message_type_arg,
            context,
        )
        if target_error:
            return target_error
        if resolved_target_id is None or resolved_message_type is None:
            return "图片生成成功，但缺少发送目标参数"

        send_timeout = get_request_timeout(60.0)
        if registered_record is not None:
            result = await _send_registered_record(
                registered_record,
                resolved_target_id,
                resolved_message_type,
                context,
            )
        elif generated_image.image_url:
            result = await _download_and_send(
                generated_image.image_url,
                resolved_target_id,
                resolved_message_type,
                send_timeout,
                context,
            )
        elif generated_image.image_bytes is not None:
            result = await _save_and_send(
                generated_image.image_bytes,
                resolved_target_id,
                resolved_message_type,
                context,
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
