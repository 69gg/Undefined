"""Load domains config section."""

from __future__ import annotations

# 配置分段加载：按 table 解析 TOML → ctx 字段 dict

import logging
from typing import Any

from ..domain_parsers import (
    _parse_api_config,
    _parse_automations_config,
    _parse_cognitive_config,
    _parse_memes_config,
    _parse_message_batcher_config,
    _parse_naga_config,
    _parse_prompt_file_includes,
    _parse_prompt_system_info_config,
    _parse_render_cache_config,
    _parse_weixin_config,
)
from ..models import ChiliarchConfig
from ..env_registry import ENV_REGISTRY
from ..coercers import _get_value, _coerce_bool
from ..parsers import (
    _parse_image_edit_model_config,
    _parse_image_gen_config,
    _parse_image_gen_model_config,
)
from ..webui_settings import parse_webui_settings

logger = logging.getLogger(__name__)


def load_domains(data: dict[str, Any]) -> dict[str, Any]:
    # 子域配置：WebUI/API/认知/表情包/合并器/Naga/生图等，与 core/models 段解耦
    webui_settings = parse_webui_settings(data)
    api_config = _parse_api_config(data)

    cognitive = _parse_cognitive_config(data)
    memes = _parse_memes_config(data)
    message_batcher = _parse_message_batcher_config(data)
    automations = _parse_automations_config(data)
    prompt_system_info = _parse_prompt_system_info_config(data)
    prompt_file_includes = _parse_prompt_file_includes(data)
    render_cache = _parse_render_cache_config(data)
    naga = _parse_naga_config(data)
    weixin = _parse_weixin_config(data)
    chiliarch_defaults = ChiliarchConfig()
    chiliarch_values: dict[str, Any] = {}
    for field_name in (
        "state_path",
        "logical_identity",
        "display_name",
        "introduction",
    ):
        path = ("chiliarch", field_name)
        raw = _get_value(data, path, ENV_REGISTRY[path])
        chiliarch_values[field_name] = (
            str(raw) if raw is not None else getattr(chiliarch_defaults, field_name)
        )
    capacity = _get_value(
        data, ("chiliarch", "max_concurrent_tasks"), "CHILIARCH_MAX_CONCURRENT_TASKS"
    )
    if isinstance(capacity, bool) or isinstance(capacity, float):
        raise ValueError("chiliarch.max_concurrent_tasks 必须为正整数")
    chiliarch = ChiliarchConfig(
        enabled=_coerce_bool(
            _get_value(data, ("chiliarch", "enabled"), "CHILIARCH_ENABLED"), False
        ),
        max_concurrent_tasks=int(capacity) if capacity is not None else 1,
        **chiliarch_values,
    )
    models_image_gen = _parse_image_gen_model_config(data)
    models_image_edit = _parse_image_edit_model_config(data)
    image_gen = _parse_image_gen_config(data)

    return {
        "webui_url": webui_settings.url,
        "webui_port": webui_settings.port,
        "webui_password": webui_settings.password,
        "webui_autostart_bot": webui_settings.autostart_bot,
        "webui_check_updates": webui_settings.check_updates,
        "webui_stop_timeout_seconds": webui_settings.stop_timeout_seconds,
        "api": api_config,
        "cognitive": cognitive,
        "memes": memes,
        "message_batcher": message_batcher,
        "automations": automations,
        "prompt_system_info": prompt_system_info,
        "prompt_file_includes": prompt_file_includes,
        "render_cache": render_cache,
        "naga": naga,
        "weixin": weixin,
        "chiliarch": chiliarch,
        "image_gen": image_gen,
        "models_image_gen": models_image_gen,
        "models_image_edit": models_image_edit,
    }
