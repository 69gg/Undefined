"""Load history_skills config section."""

from __future__ import annotations

# 配置分段加载：按 table 解析 TOML → ctx 字段 dict

import logging
from pathlib import Path
from typing import Any, Optional

from ..coercers import (
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_str,
    _coerce_str_list,
    _get_value,
    _normalize_queue_interval,
)

logger = logging.getLogger(__name__)


def load_history_skills(
    data: dict[str, Any], *, config_path: Optional[Path] = None
) -> dict[str, Any]:
    token_usage_max_size_mb = _coerce_int(
        _get_value(data, ("token_usage", "max_size_mb"), "TOKEN_USAGE_MAX_SIZE_MB"),
        5,
    )
    token_usage_max_archives = _coerce_int(
        _get_value(data, ("token_usage", "max_archives"), "TOKEN_USAGE_MAX_ARCHIVES"),
        30,
    )
    token_usage_max_total_mb = _coerce_int(
        _get_value(data, ("token_usage", "max_total_mb"), "TOKEN_USAGE_MAX_TOTAL_MB"),
        0,
    )
    token_usage_archive_prune_mode = _coerce_str(
        _get_value(
            data,
            ("token_usage", "archive_prune_mode"),
            "TOKEN_USAGE_ARCHIVE_PRUNE_MODE",
        ),
        "delete",
    )

    history_max_records = max(
        0,
        _coerce_int(
            _get_value(data, ("history", "max_records"), "HISTORY_MAX_RECORDS"),
            10000,
        ),
    )
    history_filtered_result_limit = max(
        1,
        _coerce_int(
            _get_value(
                data,
                ("history", "filtered_result_limit"),
                "HISTORY_FILTERED_RESULT_LIMIT",
            ),
            200,
        ),
    )
    history_search_scan_limit = max(
        1,
        _coerce_int(
            _get_value(
                data,
                ("history", "search_scan_limit"),
                "HISTORY_SEARCH_SCAN_LIMIT",
            ),
            10000,
        ),
    )
    history_summary_fetch_limit = max(
        1,
        _coerce_int(
            _get_value(
                data,
                ("history", "summary_fetch_limit"),
                "HISTORY_SUMMARY_FETCH_LIMIT",
            ),
            1000,
        ),
    )
    history_summary_time_fetch_limit = max(
        1,
        _coerce_int(
            _get_value(
                data,
                ("history", "summary_time_fetch_limit"),
                "HISTORY_SUMMARY_TIME_FETCH_LIMIT",
            ),
            5000,
        ),
    )
    history_onebot_fetch_limit = max(
        1,
        _coerce_int(
            _get_value(
                data,
                ("history", "onebot_fetch_limit"),
                "HISTORY_ONEBOT_FETCH_LIMIT",
            ),
            10000,
        ),
    )
    history_group_analysis_limit = max(
        1,
        _coerce_int(
            _get_value(
                data,
                ("history", "group_analysis_limit"),
                "HISTORY_GROUP_ANALYSIS_LIMIT",
            ),
            500,
        ),
    )
    attachment_use_proxy = _coerce_bool(
        _get_value(data, ("attachments", "use_proxy"), "ATTACHMENTS_USE_PROXY"), False
    )
    attachment_remote_download_max_size_mb = max(
        0,
        _coerce_int(
            _get_value(
                data,
                ("attachments", "remote_download_max_size_mb"),
                "ATTACHMENTS_REMOTE_DOWNLOAD_MAX_SIZE_MB",
            ),
            25,
        ),
    )
    attachment_cache_max_total_size_mb = max(
        0,
        _coerce_int(
            _get_value(
                data,
                ("attachments", "cache_max_total_size_mb"),
                "ATTACHMENTS_CACHE_MAX_TOTAL_SIZE_MB",
            ),
            0,
        ),
    )
    attachment_cache_max_records = max(
        0,
        _coerce_int(
            _get_value(
                data,
                ("attachments", "cache_max_records"),
                "ATTACHMENTS_CACHE_MAX_RECORDS",
            ),
            2000,
        ),
    )
    attachment_cache_max_age_days = max(
        0,
        _coerce_int(
            _get_value(
                data,
                ("attachments", "cache_max_age_days"),
                "ATTACHMENTS_CACHE_MAX_AGE_DAYS",
            ),
            7,
        ),
    )
    attachment_url_reference_max_records = max(
        0,
        _coerce_int(
            _get_value(
                data,
                ("attachments", "url_reference_max_records"),
                "ATTACHMENTS_URL_REFERENCE_MAX_RECORDS",
            ),
            2000,
        ),
    )
    attachment_url_max_length = max(
        0,
        _coerce_int(
            _get_value(
                data,
                ("attachments", "url_max_length"),
                "ATTACHMENTS_URL_MAX_LENGTH",
            ),
            8192,
        ),
    )

    skills_hot_reload = _coerce_bool(
        _get_value(data, ("skills", "hot_reload"), "SKILLS_HOT_RELOAD"), True
    )
    # interval/debounce 同时驱动 skills 目录扫描与 config.toml 热重载 watcher
    skills_hot_reload_interval = _coerce_float(
        _get_value(
            data, ("skills", "hot_reload_interval"), "SKILLS_HOT_RELOAD_INTERVAL"
        ),
        2.0,
    )
    skills_hot_reload_interval = _normalize_queue_interval(skills_hot_reload_interval)
    skills_hot_reload_debounce = _coerce_float(
        _get_value(
            data, ("skills", "hot_reload_debounce"), "SKILLS_HOT_RELOAD_DEBOUNCE"
        ),
        0.5,
    )
    skills_hot_reload_debounce = _normalize_queue_interval(skills_hot_reload_debounce)

    agent_intro_autogen_enabled = _coerce_bool(
        _get_value(
            data,
            ("skills", "intro_autogen_enabled"),
            "AGENT_INTRO_AUTOGEN_ENABLED",
        ),
        True,
    )
    agent_intro_autogen_queue_interval = _coerce_float(
        _get_value(
            data,
            ("skills", "intro_autogen_queue_interval"),
            "AGENT_INTRO_AUTOGEN_QUEUE_INTERVAL",
        ),
        1.0,
    )
    agent_intro_autogen_queue_interval = _normalize_queue_interval(
        agent_intro_autogen_queue_interval
    )
    agent_intro_autogen_max_tokens = _coerce_int(
        _get_value(
            data,
            ("skills", "intro_autogen_max_tokens"),
            "AGENT_INTRO_AUTOGEN_MAX_TOKENS",
        ),
        8192,
    )
    agent_intro_hash_path = _coerce_str(
        _get_value(data, ("skills", "intro_hash_path"), "AGENT_INTRO_HASH_PATH"),
        ".cache/agent_intro_hashes.json",
    )

    prefetch_tools_raw = _get_value(
        data, ("skills", "prefetch_tools"), "PREFETCH_TOOLS"
    )
    prefetch_tools = _coerce_str_list(prefetch_tools_raw)
    if not prefetch_tools and prefetch_tools_raw is None:
        prefetch_tools = ["get_current_time"]
    prefetch_tools_hide = _coerce_bool(
        _get_value(data, ("skills", "prefetch_tools_hide"), "PREFETCH_TOOLS_HIDE"),
        True,
    )
    tool_search_enabled = _coerce_bool(
        _get_value(data, ("skills", "tool_search_enabled"), "TOOL_SEARCH_ENABLED"),
        False,
    )
    tool_search_always_loaded_raw = _get_value(
        data,
        ("skills", "tool_search_always_loaded"),
        "TOOL_SEARCH_ALWAYS_LOADED",
    )
    tool_search_always_loaded = _coerce_str_list(tool_search_always_loaded_raw)
    if tool_search_always_loaded_raw is None:
        tool_search_always_loaded = ["send_message", "end"]
    tool_search_max_results = max(
        1,
        _coerce_int(
            _get_value(
                data,
                ("skills", "tool_search_max_results"),
                "TOOL_SEARCH_MAX_RESULTS",
            ),
            5,
        ),
    )

    return {
        "token_usage_max_size_mb": token_usage_max_size_mb,
        "token_usage_max_archives": token_usage_max_archives,
        "token_usage_max_total_mb": token_usage_max_total_mb,
        "token_usage_archive_prune_mode": token_usage_archive_prune_mode,
        "history_max_records": history_max_records,
        "history_filtered_result_limit": history_filtered_result_limit,
        "history_search_scan_limit": history_search_scan_limit,
        "history_summary_fetch_limit": history_summary_fetch_limit,
        "history_summary_time_fetch_limit": history_summary_time_fetch_limit,
        "history_onebot_fetch_limit": history_onebot_fetch_limit,
        "history_group_analysis_limit": history_group_analysis_limit,
        "attachment_use_proxy": attachment_use_proxy,
        "attachment_remote_download_max_size_mb": attachment_remote_download_max_size_mb,
        "attachment_cache_max_total_size_mb": attachment_cache_max_total_size_mb,
        "attachment_cache_max_records": attachment_cache_max_records,
        "attachment_cache_max_age_days": attachment_cache_max_age_days,
        "attachment_url_reference_max_records": attachment_url_reference_max_records,
        "attachment_url_max_length": attachment_url_max_length,
        "skills_hot_reload": skills_hot_reload,
        "skills_hot_reload_interval": skills_hot_reload_interval,
        "skills_hot_reload_debounce": skills_hot_reload_debounce,
        "agent_intro_autogen_enabled": agent_intro_autogen_enabled,
        "agent_intro_autogen_queue_interval": agent_intro_autogen_queue_interval,
        "agent_intro_autogen_max_tokens": agent_intro_autogen_max_tokens,
        "agent_intro_hash_path": agent_intro_hash_path,
        "prefetch_tools": prefetch_tools,
        "prefetch_tools_hide": prefetch_tools_hide,
        "tool_search_enabled": tool_search_enabled,
        "tool_search_always_loaded": tool_search_always_loaded,
        "tool_search_max_results": tool_search_max_results,
    }
