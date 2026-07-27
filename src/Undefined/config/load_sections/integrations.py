"""Load integrations config section."""

from __future__ import annotations

# 配置分段加载：按 table 解析 TOML → ctx 字段 dict

import logging
from pathlib import Path
from typing import Any, Optional

from ..coercers import (
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_int_list,
    _coerce_str,
    _coerce_str_list,
    _get_value,
    _normalize_base_url,
)

logger = logging.getLogger(__name__)

_DEFAULT_GITHUB_REQUEST_TIMEOUT_SECONDS: float = 10.0
_DEFAULT_GITHUB_REQUEST_RETRIES: int = 2
_MAX_GITHUB_REQUEST_TIMEOUT_SECONDS: float = 60.0
_MAX_GITHUB_REQUEST_RETRIES: int = 5
_DEFAULT_GITHUB_AUTO_EXTRACT_MAX_ITEMS: int = 3
_MAX_GITHUB_AUTO_EXTRACT_MAX_ITEMS: int = 10
_DEFAULT_LXMUSIC2API_BASE_URL: str = "http://127.0.0.1:3000"


def load_integrations(
    data: dict[str, Any], *, config_path: Optional[Path] = None
) -> dict[str, Any]:
    bilibili_use_proxy = _coerce_bool(
        _get_value(data, ("bilibili", "use_proxy"), "BILIBILI_USE_PROXY"), False
    )
    bilibili_auto_extract_enabled = _coerce_bool(
        _get_value(data, ("bilibili", "auto_extract_enabled"), None), False
    )
    # 功能级白名单为空时，运行时回退到全局 access 控制（见 Config.is_*_allowed）
    bilibili_cookie = _coerce_str(_get_value(data, ("bilibili", "cookie"), None), "")
    if not bilibili_cookie:
        # 兼容旧配置项：bilibili.sessdata
        bilibili_cookie = _coerce_str(
            _get_value(data, ("bilibili", "sessdata"), None), ""
        )
    bilibili_prefer_quality = _coerce_int(
        _get_value(data, ("bilibili", "prefer_quality"), None), 80
    )
    bilibili_max_duration = _coerce_int(
        _get_value(data, ("bilibili", "max_duration"), None), 600
    )
    bilibili_max_file_size = _coerce_int(
        _get_value(data, ("bilibili", "max_file_size"), None), 100
    )
    bilibili_oversize_strategy = _coerce_str(
        _get_value(data, ("bilibili", "oversize_strategy"), None), "downgrade"
    )
    if bilibili_oversize_strategy not in ("downgrade", "info"):
        bilibili_oversize_strategy = "downgrade"
    bilibili_danmaku_enabled = _coerce_bool(
        _get_value(data, ("bilibili", "danmaku_enabled"), None), True
    )
    bilibili_danmaku_batch_size = _coerce_int(
        _get_value(data, ("bilibili", "danmaku_batch_size"), None), 100
    )
    if bilibili_danmaku_batch_size <= 0:
        bilibili_danmaku_batch_size = 100
    bilibili_danmaku_max_count = _coerce_int(
        _get_value(data, ("bilibili", "danmaku_max_count"), None), 0
    )
    if bilibili_danmaku_max_count < 0:
        bilibili_danmaku_max_count = 0
    bilibili_auto_extract_group_ids = _coerce_int_list(
        _get_value(data, ("bilibili", "auto_extract_group_ids"), None)
    )
    bilibili_auto_extract_private_ids = _coerce_int_list(
        _get_value(data, ("bilibili", "auto_extract_private_ids"), None)
    )

    # Douyin 配置
    douyin_use_proxy = _coerce_bool(
        _get_value(data, ("douyin", "use_proxy"), "DOUYIN_USE_PROXY"), False
    )
    douyin_auto_extract_enabled = _coerce_bool(
        _get_value(data, ("douyin", "auto_extract_enabled"), None), False
    )
    douyin_max_duration = _coerce_int(
        _get_value(data, ("douyin", "max_duration"), None), 600
    )
    if douyin_max_duration < 0:
        douyin_max_duration = 600
    douyin_max_file_size = _coerce_int(
        _get_value(data, ("douyin", "max_file_size"), None), 100
    )
    if douyin_max_file_size < 0:
        douyin_max_file_size = 100
    douyin_prefer_ratios = _coerce_str_list(
        _get_value(data, ("douyin", "prefer_ratios"), None)
    )
    allowed_ratios = ("1080p", "720p", "540p", "360p")
    douyin_prefer_ratios = [
        ratio for ratio in douyin_prefer_ratios if ratio in allowed_ratios
    ] or list(allowed_ratios)
    douyin_auto_extract_group_ids = _coerce_int_list(
        _get_value(data, ("douyin", "auto_extract_group_ids"), None)
    )
    douyin_auto_extract_private_ids = _coerce_int_list(
        _get_value(data, ("douyin", "auto_extract_private_ids"), None)
    )
    douyin_auto_extract_max_items = _coerce_int(
        _get_value(data, ("douyin", "auto_extract_max_items"), None), 3
    )
    if douyin_auto_extract_max_items <= 0:
        douyin_auto_extract_max_items = 3
    if douyin_auto_extract_max_items > 10:
        douyin_auto_extract_max_items = 10

    # arXiv 配置
    arxiv_use_proxy = _coerce_bool(
        _get_value(data, ("arxiv", "use_proxy"), "ARXIV_USE_PROXY"), False
    )
    arxiv_auto_extract_enabled = _coerce_bool(
        _get_value(data, ("arxiv", "auto_extract_enabled"), None), False
    )
    arxiv_max_file_size = _coerce_int(
        _get_value(data, ("arxiv", "max_file_size"), None), 100
    )
    if arxiv_max_file_size < 0:
        arxiv_max_file_size = 100
    arxiv_auto_extract_group_ids = _coerce_int_list(
        _get_value(data, ("arxiv", "auto_extract_group_ids"), None)
    )
    arxiv_auto_extract_private_ids = _coerce_int_list(
        _get_value(data, ("arxiv", "auto_extract_private_ids"), None)
    )
    arxiv_auto_extract_max_items = _coerce_int(
        _get_value(data, ("arxiv", "auto_extract_max_items"), None), 5
    )
    if arxiv_auto_extract_max_items <= 0:
        arxiv_auto_extract_max_items = 5
    if arxiv_auto_extract_max_items > 20:
        arxiv_auto_extract_max_items = 20
    arxiv_author_preview_limit = _coerce_int(
        _get_value(data, ("arxiv", "author_preview_limit"), None), 20
    )
    if arxiv_author_preview_limit <= 0:
        arxiv_author_preview_limit = 20
    if arxiv_author_preview_limit > 100:
        arxiv_author_preview_limit = 100
    arxiv_summary_preview_chars = _coerce_int(
        _get_value(data, ("arxiv", "summary_preview_chars"), None), 1000
    )
    if arxiv_summary_preview_chars <= 0:
        arxiv_summary_preview_chars = 1000
    if arxiv_summary_preview_chars > 8000:
        arxiv_summary_preview_chars = 8000

    # GitHub 配置
    github_use_proxy = _coerce_bool(
        _get_value(data, ("github", "use_proxy"), "GITHUB_USE_PROXY"), False
    )
    github_auto_extract_enabled = _coerce_bool(
        _get_value(data, ("github", "auto_extract_enabled"), None), False
    )
    github_request_timeout_seconds = _coerce_float(
        _get_value(data, ("github", "request_timeout_seconds"), None),
        _DEFAULT_GITHUB_REQUEST_TIMEOUT_SECONDS,
    )
    if github_request_timeout_seconds <= 0:
        github_request_timeout_seconds = _DEFAULT_GITHUB_REQUEST_TIMEOUT_SECONDS
    if github_request_timeout_seconds > _MAX_GITHUB_REQUEST_TIMEOUT_SECONDS:
        github_request_timeout_seconds = _MAX_GITHUB_REQUEST_TIMEOUT_SECONDS
    github_request_retries = _coerce_int(
        _get_value(data, ("github", "request_retries"), None),
        _DEFAULT_GITHUB_REQUEST_RETRIES,
    )
    if github_request_retries < 0:
        github_request_retries = 0
    if github_request_retries > _MAX_GITHUB_REQUEST_RETRIES:
        github_request_retries = _MAX_GITHUB_REQUEST_RETRIES
    github_auto_extract_group_ids = _coerce_int_list(
        _get_value(data, ("github", "auto_extract_group_ids"), None)
    )
    github_auto_extract_private_ids = _coerce_int_list(
        _get_value(data, ("github", "auto_extract_private_ids"), None)
    )
    github_auto_extract_max_items = _coerce_int(
        _get_value(data, ("github", "auto_extract_max_items"), None),
        _DEFAULT_GITHUB_AUTO_EXTRACT_MAX_ITEMS,
    )
    if github_auto_extract_max_items <= 0:
        github_auto_extract_max_items = _DEFAULT_GITHUB_AUTO_EXTRACT_MAX_ITEMS
    if github_auto_extract_max_items > _MAX_GITHUB_AUTO_EXTRACT_MAX_ITEMS:
        github_auto_extract_max_items = _MAX_GITHUB_AUTO_EXTRACT_MAX_ITEMS

    # Code Delivery Agent 配置
    code_delivery_enabled = _coerce_bool(
        _get_value(data, ("code_delivery", "enabled"), None), True
    )
    code_delivery_task_root = _coerce_str(
        _get_value(data, ("code_delivery", "task_root"), None),
        "data/code_delivery",
    )
    code_delivery_docker_image = _coerce_str(
        _get_value(data, ("code_delivery", "docker_image"), None),
        "ubuntu:24.04",
    )
    code_delivery_container_name_prefix = _coerce_str(
        _get_value(data, ("code_delivery", "container_name_prefix"), None),
        "code_delivery_",
    )
    code_delivery_container_name_suffix = _coerce_str(
        _get_value(data, ("code_delivery", "container_name_suffix"), None),
        "_runner",
    )
    code_delivery_command_timeout = _coerce_int(
        _get_value(data, ("code_delivery", "default_command_timeout_seconds"), None),
        600,
    )
    if code_delivery_command_timeout < 1:
        code_delivery_command_timeout = 600
    code_delivery_max_command_output = _coerce_int(
        _get_value(data, ("code_delivery", "max_command_output_chars"), None),
        20000,
    )
    if code_delivery_max_command_output < 1:
        code_delivery_max_command_output = 20000
    code_delivery_default_archive_format = _coerce_str(
        _get_value(data, ("code_delivery", "default_archive_format"), None),
        "zip",
    )
    if code_delivery_default_archive_format not in ("zip", "tar.gz"):
        code_delivery_default_archive_format = "zip"
    code_delivery_max_archive_size_mb = _coerce_int(
        _get_value(data, ("code_delivery", "max_archive_size_mb"), None), 200
    )
    if code_delivery_max_archive_size_mb < 1:
        code_delivery_max_archive_size_mb = 200
    code_delivery_cleanup_on_finish = _coerce_bool(
        _get_value(data, ("code_delivery", "cleanup_on_finish"), None), True
    )
    code_delivery_cleanup_on_start = _coerce_bool(
        _get_value(data, ("code_delivery", "cleanup_on_start"), None), True
    )
    code_delivery_llm_max_retries = _coerce_int(
        _get_value(data, ("code_delivery", "llm_max_retries_per_request"), None),
        5,
    )
    if code_delivery_llm_max_retries < 0:
        code_delivery_llm_max_retries = 5
    code_delivery_notify_on_llm_failure = _coerce_bool(
        _get_value(data, ("code_delivery", "notify_on_llm_failure"), None),
        True,
    )
    code_delivery_container_memory_limit = _coerce_str(
        _get_value(data, ("code_delivery", "container_memory_limit"), None),
        "",
    )
    code_delivery_container_cpu_limit = _coerce_str(
        _get_value(data, ("code_delivery", "container_cpu_limit"), None),
        "",
    )
    code_delivery_command_blacklist_raw = _get_value(
        data, ("code_delivery", "command_blacklist"), None
    )
    if isinstance(code_delivery_command_blacklist_raw, list):
        code_delivery_command_blacklist = [
            str(x) for x in code_delivery_command_blacklist_raw
        ]
    # 否则分支
    else:
        code_delivery_command_blacklist = []

    # messages 工具集配置
    messages_use_proxy = _coerce_bool(
        _get_value(data, ("messages", "use_proxy"), "MESSAGES_USE_PROXY"), False
    )
    messages_send_text_file_max_size_kb = _coerce_int(
        _get_value(
            data,
            ("messages", "send_text_file_max_size_kb"),
            "MESSAGES_SEND_TEXT_FILE_MAX_SIZE_KB",
        ),
        512,
    )
    if messages_send_text_file_max_size_kb <= 0:
        messages_send_text_file_max_size_kb = 512

    messages_send_url_file_max_size_mb = _coerce_int(
        _get_value(
            data,
            ("messages", "send_url_file_max_size_mb"),
            "MESSAGES_SEND_URL_FILE_MAX_SIZE_MB",
        ),
        100,
    )
    if messages_send_url_file_max_size_mb <= 0:
        messages_send_url_file_max_size_mb = 100

    # lxmusic2api 音乐工具集配置
    lxmusic2api_base_url = _normalize_base_url(
        _coerce_str(
            _get_value(
                data,
                ("lxmusic2api", "base_url"),
                "LXMUSIC2API_BASE_URL",
            ),
            _DEFAULT_LXMUSIC2API_BASE_URL,
        ),
        _DEFAULT_LXMUSIC2API_BASE_URL,
    )
    lxmusic2api_api_key = _coerce_str(
        _get_value(
            data,
            ("lxmusic2api", "api_key"),
            "LXMUSIC2API_API_KEY",
        ),
        "",
    )

    return {
        "bilibili_use_proxy": bilibili_use_proxy,
        "bilibili_auto_extract_enabled": bilibili_auto_extract_enabled,
        "bilibili_cookie": bilibili_cookie,
        "bilibili_prefer_quality": bilibili_prefer_quality,
        "bilibili_max_duration": bilibili_max_duration,
        "bilibili_max_file_size": bilibili_max_file_size,
        "bilibili_oversize_strategy": bilibili_oversize_strategy,
        "bilibili_danmaku_enabled": bilibili_danmaku_enabled,
        "bilibili_danmaku_batch_size": bilibili_danmaku_batch_size,
        "bilibili_danmaku_max_count": bilibili_danmaku_max_count,
        "bilibili_auto_extract_group_ids": bilibili_auto_extract_group_ids,
        "bilibili_auto_extract_private_ids": bilibili_auto_extract_private_ids,
        "douyin_use_proxy": douyin_use_proxy,
        "douyin_auto_extract_enabled": douyin_auto_extract_enabled,
        "douyin_max_duration": douyin_max_duration,
        "douyin_max_file_size": douyin_max_file_size,
        "douyin_prefer_ratios": douyin_prefer_ratios,
        "douyin_auto_extract_group_ids": douyin_auto_extract_group_ids,
        "douyin_auto_extract_private_ids": douyin_auto_extract_private_ids,
        "douyin_auto_extract_max_items": douyin_auto_extract_max_items,
        "arxiv_use_proxy": arxiv_use_proxy,
        "arxiv_auto_extract_enabled": arxiv_auto_extract_enabled,
        "arxiv_max_file_size": arxiv_max_file_size,
        "arxiv_auto_extract_group_ids": arxiv_auto_extract_group_ids,
        "arxiv_auto_extract_private_ids": arxiv_auto_extract_private_ids,
        "arxiv_auto_extract_max_items": arxiv_auto_extract_max_items,
        "arxiv_author_preview_limit": arxiv_author_preview_limit,
        "arxiv_summary_preview_chars": arxiv_summary_preview_chars,
        "github_use_proxy": github_use_proxy,
        "github_auto_extract_enabled": github_auto_extract_enabled,
        "github_request_timeout_seconds": github_request_timeout_seconds,
        "github_request_retries": github_request_retries,
        "github_auto_extract_group_ids": github_auto_extract_group_ids,
        "github_auto_extract_private_ids": github_auto_extract_private_ids,
        "github_auto_extract_max_items": github_auto_extract_max_items,
        "code_delivery_enabled": code_delivery_enabled,
        "code_delivery_task_root": code_delivery_task_root,
        "code_delivery_docker_image": code_delivery_docker_image,
        "code_delivery_container_name_prefix": code_delivery_container_name_prefix,
        "code_delivery_container_name_suffix": code_delivery_container_name_suffix,
        "code_delivery_command_timeout": code_delivery_command_timeout,
        "code_delivery_max_command_output": code_delivery_max_command_output,
        "code_delivery_default_archive_format": code_delivery_default_archive_format,
        "code_delivery_max_archive_size_mb": code_delivery_max_archive_size_mb,
        "code_delivery_cleanup_on_finish": code_delivery_cleanup_on_finish,
        "code_delivery_cleanup_on_start": code_delivery_cleanup_on_start,
        "code_delivery_llm_max_retries": code_delivery_llm_max_retries,
        "code_delivery_notify_on_llm_failure": code_delivery_notify_on_llm_failure,
        "code_delivery_container_memory_limit": code_delivery_container_memory_limit,
        "code_delivery_container_cpu_limit": code_delivery_container_cpu_limit,
        "code_delivery_command_blacklist": code_delivery_command_blacklist,
        "messages_use_proxy": messages_use_proxy,
        "messages_send_text_file_max_size_kb": messages_send_text_file_max_size_kb,
        "messages_send_url_file_max_size_mb": messages_send_url_file_max_size_mb,
        "lxmusic2api_base_url": lxmusic2api_base_url,
        "lxmusic2api_api_key": lxmusic2api_api_key,
    }
