"""Domain configuration parsers (cognitive, memes, API, naga)."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

from .coercers import (
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_str,
    _coerce_int_list,
    _coerce_str_list,
)
from .models import (
    APIConfig,
    CognitiveConfig,
    MemeConfig,
    NagaConfig,
)

DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8788
DEFAULT_API_AUTH_KEY = "changeme"


def _parse_cognitive_config(data: dict[str, Any]) -> CognitiveConfig:
    cog = data.get("cognitive", {})
    vs = cog.get("vector_store", {}) if isinstance(cog, dict) else {}
    q = cog.get("query", {}) if isinstance(cog, dict) else {}
    hist = cog.get("historian", {}) if isinstance(cog, dict) else {}
    prof = cog.get("profile", {}) if isinstance(cog, dict) else {}
    que = cog.get("queue", {}) if isinstance(cog, dict) else {}
    return CognitiveConfig(
        enabled=_coerce_bool(
            cog.get("enabled") if isinstance(cog, dict) else None, True
        ),
        bot_name=_coerce_str(
            cog.get("bot_name") if isinstance(cog, dict) else None,
            "Undefined",
        ),
        vector_store_path=_coerce_str(
            vs.get("path") if isinstance(vs, dict) else None,
            "data/cognitive/chromadb",
        ),
        queue_path=_coerce_str(
            que.get("path") if isinstance(que, dict) else None,
            "data/cognitive/queues",
        ),
        profiles_path=_coerce_str(
            prof.get("path") if isinstance(prof, dict) else None,
            "data/cognitive/profiles",
        ),
        auto_top_k=_coerce_int(q.get("auto_top_k") if isinstance(q, dict) else None, 3),
        auto_scope_candidate_multiplier=_coerce_int(
            q.get("auto_scope_candidate_multiplier") if isinstance(q, dict) else None,
            2,
        ),
        auto_current_group_boost=_coerce_float(
            q.get("auto_current_group_boost") if isinstance(q, dict) else None,
            1.15,
        ),
        auto_current_private_boost=_coerce_float(
            q.get("auto_current_private_boost") if isinstance(q, dict) else None,
            1.25,
        ),
        enable_rerank=_coerce_bool(
            q.get("enable_rerank") if isinstance(q, dict) else None, True
        ),
        recent_end_summaries_inject_k=_coerce_int(
            q.get("recent_end_summaries_inject_k") if isinstance(q, dict) else None,
            30,
        ),
        time_decay_enabled=_coerce_bool(
            q.get("time_decay_enabled") if isinstance(q, dict) else None, True
        ),
        time_decay_half_life_days_auto=_coerce_float(
            q.get("time_decay_half_life_days_auto") if isinstance(q, dict) else None,
            14.0,
        ),
        time_decay_half_life_days_tool=_coerce_float(
            q.get("time_decay_half_life_days_tool") if isinstance(q, dict) else None,
            60.0,
        ),
        time_decay_boost=_coerce_float(
            q.get("time_decay_boost") if isinstance(q, dict) else None, 0.2
        ),
        time_decay_min_similarity=_coerce_float(
            q.get("time_decay_min_similarity") if isinstance(q, dict) else None,
            0.35,
        ),
        tool_default_top_k=_coerce_int(
            q.get("tool_default_top_k") if isinstance(q, dict) else None, 12
        ),
        profile_top_k=_coerce_int(
            q.get("profile_top_k") if isinstance(q, dict) else None, 8
        ),
        rerank_candidate_multiplier=_coerce_int(
            q.get("rerank_candidate_multiplier") if isinstance(q, dict) else None, 3
        ),
        rewrite_max_retry=_coerce_int(
            hist.get("rewrite_max_retry") if isinstance(hist, dict) else None, 2
        ),
        historian_recent_messages_inject_k=_coerce_int(
            hist.get("recent_messages_inject_k") if isinstance(hist, dict) else None,
            12,
        ),
        historian_recent_message_line_max_len=_coerce_int(
            hist.get("recent_message_line_max_len") if isinstance(hist, dict) else None,
            240,
        ),
        historian_source_message_max_len=_coerce_int(
            hist.get("source_message_max_len") if isinstance(hist, dict) else None,
            800,
        ),
        poll_interval_seconds=_coerce_float(
            hist.get("poll_interval_seconds") if isinstance(hist, dict) else None,
            1.0,
        ),
        stale_job_timeout_seconds=_coerce_float(
            hist.get("stale_job_timeout_seconds") if isinstance(hist, dict) else None,
            300.0,
        ),
        profile_revision_keep=_coerce_int(
            prof.get("revision_keep") if isinstance(prof, dict) else None, 5
        ),
        failed_max_age_days=_coerce_int(
            que.get("failed_max_age_days") if isinstance(que, dict) else None, 30
        ),
        failed_max_files=_coerce_int(
            que.get("failed_max_files") if isinstance(que, dict) else None, 500
        ),
        failed_cleanup_interval=_coerce_int(
            que.get("failed_cleanup_interval") if isinstance(que, dict) else None,
            100,
        ),
        job_max_retries=_coerce_int(
            que.get("job_max_retries") if isinstance(que, dict) else None, 3
        ),
    )


def _parse_memes_config(data: dict[str, Any]) -> MemeConfig:
    section_raw = data.get("memes", {})
    section = section_raw if isinstance(section_raw, dict) else {}
    return MemeConfig(
        enabled=_coerce_bool(section.get("enabled"), True),
        query_default_mode=_coerce_str(section.get("query_default_mode"), "hybrid"),
        max_source_image_bytes=max(
            1,
            _coerce_int(section.get("max_source_image_bytes"), 500 * 1024),
        ),
        blob_dir=_coerce_str(section.get("blob_dir"), "data/memes/blobs"),
        preview_dir=_coerce_str(section.get("preview_dir"), "data/memes/previews"),
        db_path=_coerce_str(section.get("db_path"), "data/memes/memes.sqlite3"),
        vector_store_path=_coerce_str(
            section.get("vector_store_path"), "data/memes/chromadb"
        ),
        queue_path=_coerce_str(section.get("queue_path"), "data/memes/queues"),
        max_items=max(1, _coerce_int(section.get("max_items"), 10000)),
        max_total_bytes=max(
            1,
            _coerce_int(section.get("max_total_bytes"), 5 * 1024 * 1024 * 1024),
        ),
        allow_gif=_coerce_bool(section.get("allow_gif"), True),
        auto_ingest_group=_coerce_bool(section.get("auto_ingest_group"), True),
        auto_ingest_private=_coerce_bool(section.get("auto_ingest_private"), True),
        keyword_top_k=max(1, _coerce_int(section.get("keyword_top_k"), 30)),
        semantic_top_k=max(1, _coerce_int(section.get("semantic_top_k"), 30)),
        rerank_top_k=max(1, _coerce_int(section.get("rerank_top_k"), 20)),
        worker_max_concurrency=max(
            1, _coerce_int(section.get("worker_max_concurrency"), 4)
        ),
    )


def _parse_api_config(data: dict[str, Any]) -> APIConfig:
    section_raw = data.get("api", {})
    section = section_raw if isinstance(section_raw, dict) else {}

    enabled = _coerce_bool(section.get("enabled"), True)
    host = _coerce_str(section.get("host"), DEFAULT_API_HOST)
    port = _coerce_int(section.get("port"), DEFAULT_API_PORT)
    if port <= 0 or port > 65535:
        port = DEFAULT_API_PORT

    auth_key = _coerce_str(section.get("auth_key"), DEFAULT_API_AUTH_KEY)
    if not auth_key:
        auth_key = DEFAULT_API_AUTH_KEY

    openapi_enabled = _coerce_bool(section.get("openapi_enabled"), True)

    tool_invoke_enabled = _coerce_bool(section.get("tool_invoke_enabled"), False)
    tool_invoke_expose = _coerce_str(
        section.get("tool_invoke_expose"), "tools+toolsets"
    )
    valid_expose = {"tools", "toolsets", "tools+toolsets", "agents", "all"}
    if tool_invoke_expose not in valid_expose:
        tool_invoke_expose = "tools+toolsets"
    tool_invoke_allowlist = _coerce_str_list(section.get("tool_invoke_allowlist"))
    tool_invoke_denylist = _coerce_str_list(section.get("tool_invoke_denylist"))
    tool_invoke_timeout = _coerce_int(section.get("tool_invoke_timeout"), 120)
    if tool_invoke_timeout <= 0:
        tool_invoke_timeout = 120
    tool_invoke_callback_timeout = _coerce_int(
        section.get("tool_invoke_callback_timeout"), 10
    )
    if tool_invoke_callback_timeout <= 0:
        tool_invoke_callback_timeout = 10

    return APIConfig(
        enabled=enabled,
        host=host,
        port=port,
        auth_key=auth_key,
        openapi_enabled=openapi_enabled,
        tool_invoke_enabled=tool_invoke_enabled,
        tool_invoke_expose=tool_invoke_expose,
        tool_invoke_allowlist=tool_invoke_allowlist,
        tool_invoke_denylist=tool_invoke_denylist,
        tool_invoke_timeout=tool_invoke_timeout,
        tool_invoke_callback_timeout=tool_invoke_callback_timeout,
    )


def _parse_naga_config(data: dict[str, Any]) -> NagaConfig:
    section_raw = data.get("naga", {})
    section = section_raw if isinstance(section_raw, dict) else {}

    enabled = _coerce_bool(section.get("enabled"), False)
    api_url = _coerce_str(section.get("api_url"), "")
    api_key = _coerce_str(section.get("api_key"), "")
    moderation_enabled = _coerce_bool(section.get("moderation_enabled"), True)
    allowed_groups = frozenset(_coerce_int_list(section.get("allowed_groups")))

    return NagaConfig(
        enabled=enabled,
        api_url=api_url,
        api_key=api_key,
        moderation_enabled=moderation_enabled,
        allowed_groups=allowed_groups,
    )


def _parse_easter_egg_call_mode(value: Any) -> str:
    """解析彩蛋提示模式。

    兼容旧版布尔值：
    - True  => agent
    - False => none
    """
    if isinstance(value, bool):
        return "agent" if value else "none"
    if isinstance(value, (int, float)):
        return "agent" if bool(value) else "none"
    if value is None:
        return "none"

    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return "agent"
    if text in {"false", "0", "no", "off"}:
        return "none"
    if text in {"none", "agent", "tools", "all", "clean"}:
        return text
    return "none"


def _update_dataclass(
    old_value: Any, new_value: Any, prefix: str
) -> dict[str, tuple[Any, Any]]:
    changes: dict[str, tuple[Any, Any]] = {}
    if not isinstance(old_value, type(new_value)):
        changes[prefix] = (old_value, new_value)
        return changes
    for field in fields(old_value):
        name = field.name
        old_attr = getattr(old_value, name)
        new_attr = getattr(new_value, name)
        if old_attr != new_attr:
            setattr(old_value, name, new_attr)
            changes[f"{prefix}.{name}"] = (old_attr, new_attr)
    return changes
