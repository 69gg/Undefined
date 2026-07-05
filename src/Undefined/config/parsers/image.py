"""Image model parser."""

from __future__ import annotations

# 模型配置解析：原始 dict → ChatModelConfig 等 dataclass

import logging
from typing import Any


from ..coercers import (
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_str,
    _get_model_request_params,
    _get_value,
)
from ..models import (
    ImageGenConfig,
    ImageGenModelConfig,
)

logger = logging.getLogger(__name__)


def _parse_image_gen_model_config(data: dict[str, Any]) -> ImageGenModelConfig:
    """解析 [models.image_gen] 生图模型配置"""
    return ImageGenModelConfig(
        api_url=_coerce_str(
            _get_value(
                data, ("models", "image_gen", "api_url"), "IMAGE_GEN_MODEL_API_URL"
            ),
            "",
        ),
        api_key=_coerce_str(
            _get_value(
                data, ("models", "image_gen", "api_key"), "IMAGE_GEN_MODEL_API_KEY"
            ),
            "",
        ),
        model_name=_coerce_str(
            _get_value(
                data, ("models", "image_gen", "model_name"), "IMAGE_GEN_MODEL_NAME"
            ),
            "",
        ),
        context_window_tokens=_coerce_int(
            _get_value(
                data,
                ("models", "image_gen", "context_window_tokens"),
                None,
            ),
            0,
        ),
        use_proxy=_coerce_bool(
            _get_value(
                data,
                ("models", "image_gen", "use_proxy"),
                "IMAGE_GEN_MODEL_USE_PROXY",
            ),
            False,
        ),
        request_params=_get_model_request_params(data, "image_gen"),
    )


def _parse_image_edit_model_config(data: dict[str, Any]) -> ImageGenModelConfig:
    """解析 [models.image_edit] 参考图生图模型配置"""
    return ImageGenModelConfig(
        api_url=_coerce_str(
            _get_value(
                data,
                ("models", "image_edit", "api_url"),
                "IMAGE_EDIT_MODEL_API_URL",
            ),
            "",
        ),
        api_key=_coerce_str(
            _get_value(
                data,
                ("models", "image_edit", "api_key"),
                "IMAGE_EDIT_MODEL_API_KEY",
            ),
            "",
        ),
        model_name=_coerce_str(
            _get_value(
                data,
                ("models", "image_edit", "model_name"),
                "IMAGE_EDIT_MODEL_NAME",
            ),
            "",
        ),
        context_window_tokens=_coerce_int(
            _get_value(
                data,
                ("models", "image_edit", "context_window_tokens"),
                None,
            ),
            0,
        ),
        use_proxy=_coerce_bool(
            _get_value(
                data,
                ("models", "image_edit", "use_proxy"),
                "IMAGE_EDIT_MODEL_USE_PROXY",
            ),
            False,
        ),
        request_params=_get_model_request_params(data, "image_edit"),
    )


def _parse_image_gen_config(data: dict[str, Any]) -> ImageGenConfig:
    """解析 [image_gen] 生图工具配置"""
    return ImageGenConfig(
        provider=_coerce_str(
            _get_value(data, ("image_gen", "provider"), "IMAGE_GEN_PROVIDER"),
            "xingzhige",
        ),
        xingzhige_size=_coerce_str(
            _get_value(data, ("image_gen", "xingzhige_size"), None), "1:1"
        ),
        openai_size=_coerce_str(
            _get_value(data, ("image_gen", "openai_size"), None), ""
        ),
        openai_quality=_coerce_str(
            _get_value(data, ("image_gen", "openai_quality"), None), ""
        ),
        openai_style=_coerce_str(
            _get_value(data, ("image_gen", "openai_style"), None), ""
        ),
        openai_timeout=_coerce_float(
            _get_value(data, ("image_gen", "openai_timeout"), None), 120.0
        ),
        use_proxy=_coerce_bool(
            _get_value(data, ("image_gen", "use_proxy"), "IMAGE_GEN_USE_PROXY"),
            False,
        ),
    )
