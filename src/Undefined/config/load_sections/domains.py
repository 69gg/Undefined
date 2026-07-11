"""Load domains config section."""

from __future__ import annotations

# 配置分段加载：按 table 解析 TOML → ctx 字段 dict

import logging
from pathlib import Path
from typing import Any, Optional

from ..domain_parsers import (
    _parse_api_config,
    _parse_cognitive_config,
    _parse_memes_config,
    _parse_message_batcher_config,
    _parse_naga_config,
    _parse_prompt_system_info_config,
    _parse_render_cache_config,
)
from ..parsers import (
    _parse_image_edit_model_config,
    _parse_image_gen_config,
    _parse_image_gen_model_config,
)
from ..webui_settings import load_webui_settings

logger = logging.getLogger(__name__)


def load_domains(
    data: dict[str, Any], *, config_path: Optional[Path] = None
) -> dict[str, Any]:
    # 子域配置：WebUI/API/认知/表情包/合并器/Naga/生图等，与 core/models 段解耦
    webui_settings = load_webui_settings(config_path)
    api_config = _parse_api_config(data)

    cognitive = _parse_cognitive_config(data)
    memes = _parse_memes_config(data)
    message_batcher = _parse_message_batcher_config(data)
    prompt_system_info = _parse_prompt_system_info_config(data)
    render_cache = _parse_render_cache_config(data)
    naga = _parse_naga_config(data)
    models_image_gen = _parse_image_gen_model_config(data)
    models_image_edit = _parse_image_edit_model_config(data)
    image_gen = _parse_image_gen_config(data)

    return {
        "webui_url": webui_settings.url,
        "webui_port": webui_settings.port,
        "webui_password": webui_settings.password,
        "webui_autostart_bot": webui_settings.autostart_bot,
        "webui_check_updates": webui_settings.check_updates,
        "api": api_config,
        "cognitive": cognitive,
        "memes": memes,
        "message_batcher": message_batcher,
        "prompt_system_info": prompt_system_info,
        "render_cache": render_cache,
        "naga": naga,
        "image_gen": image_gen,
        "models_image_gen": models_image_gen,
        "models_image_edit": models_image_edit,
    }
