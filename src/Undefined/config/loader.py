"""配置加载逻辑"""

from __future__ import annotations

import logging
import os
import re
import tomllib
from dataclasses import dataclass, field as dataclass_field, fields
from pathlib import Path
from typing import Any, Optional, IO

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    StrPath = str | os.PathLike[str]

    def load_dotenv(
        dotenv_path: StrPath | None = None,
        stream: IO[str] | None = None,
        verbose: bool = False,
        override: bool = False,
        interpolate: bool = True,
        encoding: str | None = "utf-8",
    ) -> bool:
        return False


from .models import (
    APIConfig,
    AgentModelConfig,
    ChatModelConfig,
    CognitiveConfig,
    EmbeddingModelConfig,
    GrokModelConfig,
    ImageGenConfig,
    ImageGenModelConfig,
    MemeConfig,
    NagaConfig,
    RerankModelConfig,
    SecurityModelConfig,
    VisionModelConfig,
)
from .coercers import (  # noqa: F401 — re-exported for backward compat
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_int_list,
    _coerce_str,
    _coerce_str_list,
    _get_model_request_params,
    _get_value,
    _normalize_base_url,
    _normalize_queue_interval,
    _normalize_str,
    _warn_env_fallback,
)
from .resolvers import (  # noqa: F401 — re-exported for backward compat
    _resolve_api_mode,
    _resolve_reasoning_effort,
    _resolve_reasoning_effort_style,
    _resolve_responses_force_stateless_replay,
    _resolve_responses_tool_choice_compat,
    _resolve_thinking_compat_flags,
)
from .admin import (  # noqa: F401 — re-exported for backward compat
    LOCAL_CONFIG_PATH,
    load_local_admins,
    save_local_admins,
)
from .webui_settings import (  # noqa: F401 — re-exported for backward compat
    DEFAULT_WEBUI_PASSWORD,
    DEFAULT_WEBUI_PORT,
    DEFAULT_WEBUI_URL,
    WebUISettings,
    load_webui_settings,
)
from .model_parsers import (
    _log_debug_info,
    _merge_admins,
    _parse_agent_model_config,
    _parse_chat_model_config,
    _parse_embedding_model_config,
    _parse_grok_model_config,
    _parse_historian_model_config,
    _parse_image_edit_model_config,
    _parse_image_gen_config,
    _parse_image_gen_model_config,
    _parse_naga_model_config,
    _parse_rerank_model_config,
    _parse_security_model_config,
    _parse_summary_model_config,
    _parse_vision_model_config,
    _verify_required_fields,
)
from .domain_parsers import (
    _parse_api_config,
    _parse_cognitive_config,
    _parse_easter_egg_call_mode,
    _parse_memes_config,
    _parse_naga_config,
    _update_dataclass,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.toml")

# Re-export symbols that external modules import from this module.
__all__ = [
    "CONFIG_PATH",
    "Config",
    "DEFAULT_WEBUI_PASSWORD",
    "DEFAULT_WEBUI_PORT",
    "DEFAULT_WEBUI_URL",
    "LOCAL_CONFIG_PATH",
    "WebUISettings",
    "load_local_admins",
    "load_toml_data",
    "load_webui_settings",
    "save_local_admins",
]


def _load_env() -> None:
    try:
        load_dotenv()
    except Exception:
        logger.debug("加载 .env 失败，继续使用 config.toml", exc_info=True)


def _build_toml_decode_hint(line: str) -> str:
    hints: list[str] = []
    if "\\" in line:
        hints.append(
            'Windows 路径建议用单引号(不转义)或双反斜杠，或直接用正斜杠，例如：path = \'D:\\AI\\bot\' / path = "D:\\\\AI\\\\bot" / path = "D:/AI/bot"'
        )
    hints.append('多行文本请用三引号，例如：prompt = """..."""')
    return "；".join(hints)


def _format_toml_decode_error(
    path: Path, text: str, exc: tomllib.TOMLDecodeError
) -> str:
    lineno: int | None = getattr(exc, "lineno", None)
    colno: int | None = getattr(exc, "colno", None)
    if not isinstance(lineno, int) or not isinstance(colno, int):
        match = re.search(r"\(at line (\d+), column (\d+)\)", str(exc))
        if match:
            lineno = int(match.group(1))
            colno = int(match.group(2))

    if isinstance(lineno, int) and lineno > 0:
        lines = text.splitlines()
        line = lines[lineno - 1] if 0 <= (lineno - 1) < len(lines) else ""
        caret_pos = max((colno or 1) - 1, 0)
        caret = " " * min(caret_pos, len(line)) + "^"
        hint = _build_toml_decode_hint(line)
        location = f"line={lineno} col={colno or 1}"
        return f"{exc} ({location})\n> {line}\n  {caret}\n提示：{hint}"
    return str(exc)


def load_toml_data(
    config_path: Optional[Path] = None, *, strict: bool = False
) -> dict[str, Any]:
    """读取 config.toml 并返回字典"""
    path = config_path or CONFIG_PATH
    if not path.exists():
        return {}
    text = ""
    try:
        text = path.read_bytes().decode("utf-8-sig")
        data = tomllib.loads(text)
        if isinstance(data, dict):
            return data
        logger.warning("config.toml 内容不是对象结构")
        return {}
    except tomllib.TOMLDecodeError as exc:
        message = _format_toml_decode_error(path, text, exc)
        logger.error("config.toml 解析失败 (%s): %s", path.resolve(), message)
        if strict:
            raise ValueError(message) from exc
        return {}
    except UnicodeDecodeError as exc:
        logger.error("config.toml 编码错误 (%s): %s", path.resolve(), exc)
        if strict:
            raise ValueError(str(exc)) from exc
        return {}
    except OSError as exc:
        logger.error("读取 config.toml 失败: %s", exc)
        if strict:
            raise ValueError(str(exc)) from exc
        return {}


@dataclass
class Config:
    """应用配置"""

    bot_qq: int
    superadmin_qq: int
    admin_qqs: list[int]
    # 访问控制模式：off / blacklist / allowlist
    access_mode: str
    # 访问控制（会话白名单 + 黑名单）
    allowed_group_ids: list[int]
    blocked_group_ids: list[int]
    allowed_private_ids: list[int]
    blocked_private_ids: list[int]
    # 是否允许超级管理员在私聊中绕过 allowed_private_ids（仅私聊收发）
    superadmin_bypass_allowlist: bool
    # 是否允许超级管理员在私聊中绕过 blocked_private_ids（仅私聊收发）
    superadmin_bypass_private_blacklist: bool
    forward_proxy_qq: int | None
    process_every_message: bool
    process_private_message: bool
    process_poke_message: bool
    keyword_reply_enabled: bool
    repeat_enabled: bool
    repeat_threshold: int
    repeat_cooldown_minutes: int
    inverted_question_enabled: bool
    context_recent_messages_limit: int
    ai_request_max_retries: int
    nagaagent_mode_enabled: bool
    onebot_ws_url: str
    onebot_token: str
    chat_model: ChatModelConfig
    vision_model: VisionModelConfig
    security_model_enabled: bool
    security_model: SecurityModelConfig
    naga_model: SecurityModelConfig
    agent_model: AgentModelConfig
    historian_model: AgentModelConfig
    summary_model: AgentModelConfig
    summary_model_configured: bool
    grok_model: GrokModelConfig
    model_pool_enabled: bool
    log_level: str
    log_file_path: str
    log_max_size: int
    log_backup_count: int
    log_tty_enabled: bool
    log_thinking: bool
    tools_dot_delimiter: str
    tools_description_truncate_enabled: bool
    tools_description_max_len: int
    tools_sanitize_verbose: bool
    tools_description_preview_len: int
    easter_egg_agent_call_message_mode: str
    token_usage_max_size_mb: int
    token_usage_max_archives: int
    token_usage_max_total_mb: int
    token_usage_archive_prune_mode: str
    history_max_records: int
    history_filtered_result_limit: int
    history_search_scan_limit: int
    history_summary_fetch_limit: int
    history_summary_time_fetch_limit: int
    history_onebot_fetch_limit: int
    history_group_analysis_limit: int
    skills_hot_reload: bool
    skills_hot_reload_interval: float
    skills_hot_reload_debounce: float
    agent_intro_autogen_enabled: bool
    agent_intro_autogen_queue_interval: float
    agent_intro_autogen_max_tokens: int
    agent_intro_hash_path: str
    searxng_url: str
    grok_search_enabled: bool
    use_proxy: bool
    http_proxy: str
    https_proxy: str
    network_request_timeout: float
    network_request_retries: int
    api_xxapi_base_url: str
    api_xingzhige_base_url: str
    api_jkyai_base_url: str
    api_seniverse_base_url: str
    weather_api_key: str
    xxapi_api_token: str
    mcp_config_path: str
    prefetch_tools: list[str]
    prefetch_tools_hide: bool
    webui_url: str
    webui_port: int
    webui_password: str
    api: APIConfig
    # Code Delivery Agent
    code_delivery_enabled: bool
    code_delivery_task_root: str
    code_delivery_docker_image: str
    code_delivery_container_name_prefix: str
    code_delivery_container_name_suffix: str
    code_delivery_command_timeout: int
    code_delivery_max_command_output: int
    code_delivery_default_archive_format: str
    code_delivery_max_archive_size_mb: int
    code_delivery_cleanup_on_finish: bool
    code_delivery_cleanup_on_start: bool
    code_delivery_llm_max_retries: int
    code_delivery_notify_on_llm_failure: bool
    code_delivery_container_memory_limit: str
    code_delivery_container_cpu_limit: str
    code_delivery_command_blacklist: list[str]
    # messages 工具集
    messages_send_text_file_max_size_kb: int
    messages_send_url_file_max_size_mb: int
    # 嵌入模型
    embedding_model: EmbeddingModelConfig
    rerank_model: RerankModelConfig
    # 知识库
    knowledge_enabled: bool
    knowledge_base_dir: str
    knowledge_auto_scan: bool
    knowledge_auto_embed: bool
    knowledge_scan_interval: float
    knowledge_embed_batch_size: int
    knowledge_chunk_size: int
    knowledge_chunk_overlap: int
    knowledge_default_top_k: int
    knowledge_enable_rerank: bool
    knowledge_rerank_top_k: int
    # Bilibili 视频提取
    bilibili_auto_extract_enabled: bool
    bilibili_cookie: str
    bilibili_prefer_quality: int
    bilibili_max_duration: int
    bilibili_max_file_size: int
    bilibili_oversize_strategy: str
    bilibili_auto_extract_group_ids: list[int]
    bilibili_auto_extract_private_ids: list[int]
    # arXiv 论文提取
    arxiv_auto_extract_enabled: bool
    arxiv_max_file_size: int
    arxiv_auto_extract_group_ids: list[int]
    arxiv_auto_extract_private_ids: list[int]
    arxiv_auto_extract_max_items: int
    arxiv_author_preview_limit: int
    arxiv_summary_preview_chars: int
    # 认知记忆
    cognitive: CognitiveConfig
    # 表情包库
    memes: MemeConfig
    # Naga 集成
    naga: NagaConfig
    # 生图工具配置
    image_gen: ImageGenConfig
    models_image_gen: ImageGenModelConfig
    models_image_edit: ImageGenModelConfig
    _allowed_group_ids_set: set[int] = dataclass_field(
        default_factory=set,
        init=False,
        repr=False,
    )
    _blocked_group_ids_set: set[int] = dataclass_field(
        default_factory=set,
        init=False,
        repr=False,
    )
    _allowed_private_ids_set: set[int] = dataclass_field(
        default_factory=set,
        init=False,
        repr=False,
    )
    _blocked_private_ids_set: set[int] = dataclass_field(
        default_factory=set,
        init=False,
        repr=False,
    )
    _bilibili_group_ids_set: set[int] = dataclass_field(
        default_factory=set,
        init=False,
        repr=False,
    )
    _bilibili_private_ids_set: set[int] = dataclass_field(
        default_factory=set,
        init=False,
        repr=False,
    )
    _arxiv_group_ids_set: set[int] = dataclass_field(
        default_factory=set,
        init=False,
        repr=False,
    )
    _arxiv_private_ids_set: set[int] = dataclass_field(
        default_factory=set,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        # 访问控制属于高频热路径，启动后缓存为 set 降低重复构建开销。
        normalized_mode = str(self.access_mode).strip().lower()
        if normalized_mode not in {"off", "blacklist", "allowlist", "legacy"}:
            normalized_mode = "off"
        self.access_mode = normalized_mode
        self._allowed_group_ids_set = {int(item) for item in self.allowed_group_ids}
        self._blocked_group_ids_set = {int(item) for item in self.blocked_group_ids}
        self._allowed_private_ids_set = {int(item) for item in self.allowed_private_ids}
        self._blocked_private_ids_set = {int(item) for item in self.blocked_private_ids}
        self._bilibili_group_ids_set = {
            int(item) for item in self.bilibili_auto_extract_group_ids
        }
        self._bilibili_private_ids_set = {
            int(item) for item in self.bilibili_auto_extract_private_ids
        }
        self._arxiv_group_ids_set = {
            int(item) for item in self.arxiv_auto_extract_group_ids
        }
        self._arxiv_private_ids_set = {
            int(item) for item in self.arxiv_auto_extract_private_ids
        }

    @classmethod
    def load(cls, config_path: Optional[Path] = None, strict: bool = True) -> "Config":
        """从 config.toml 和本地配置加载配置"""
        _load_env()
        data = load_toml_data(config_path, strict=strict)

        bot_qq = _coerce_int(_get_value(data, ("core", "bot_qq"), "BOT_QQ"), 0)
        superadmin_qq = _coerce_int(
            _get_value(data, ("core", "superadmin_qq"), "SUPERADMIN_QQ"), 0
        )
        admin_qqs = _coerce_int_list(_get_value(data, ("core", "admin_qq"), "ADMIN_QQ"))
        forward_proxy = _coerce_int(
            _get_value(data, ("core", "forward_proxy_qq"), "FORWARD_PROXY_QQ"),
            0,
        )
        forward_proxy_qq = forward_proxy if forward_proxy > 0 else None
        process_every_message = _coerce_bool(
            _get_value(
                data,
                ("core", "process_every_message"),
                "PROCESS_EVERY_MESSAGE",
            ),
            True,
        )
        process_private_message = _coerce_bool(
            _get_value(
                data,
                ("core", "process_private_message"),
                "PROCESS_PRIVATE_MESSAGE",
            ),
            True,
        )
        process_poke_message = _coerce_bool(
            _get_value(
                data,
                ("core", "process_poke_message"),
                "PROCESS_POKE_MESSAGE",
            ),
            True,
        )
        keyword_reply_raw = _get_value(
            data,
            ("easter_egg", "keyword_reply_enabled"),
            "KEYWORD_REPLY_ENABLED",
        )
        if keyword_reply_raw is None:
            # 兼容旧配置：历史上放在 [core].keyword_reply_enabled
            keyword_reply_raw = _get_value(
                data,
                ("core", "keyword_reply_enabled"),
                None,
            )
        keyword_reply_enabled = _coerce_bool(keyword_reply_raw, False)
        repeat_enabled = _coerce_bool(
            _get_value(
                data,
                ("easter_egg", "repeat_enabled"),
                "EASTER_EGG_REPEAT_ENABLED",
            ),
            False,
        )
        inverted_question_enabled = _coerce_bool(
            _get_value(
                data,
                ("easter_egg", "inverted_question_enabled"),
                "EASTER_EGG_INVERTED_QUESTION_ENABLED",
            ),
            False,
        )
        repeat_threshold = _coerce_int(
            _get_value(
                data,
                ("easter_egg", "repeat_threshold"),
                "EASTER_EGG_REPEAT_THRESHOLD",
            ),
            3,
        )
        if repeat_threshold < 2:
            repeat_threshold = 2
        if repeat_threshold > 20:
            repeat_threshold = 20
        repeat_cooldown_minutes = _coerce_int(
            _get_value(
                data,
                ("easter_egg", "repeat_cooldown_minutes"),
                "EASTER_EGG_REPEAT_COOLDOWN_MINUTES",
            ),
            60,
        )
        if repeat_cooldown_minutes < 0:
            repeat_cooldown_minutes = 0
        context_recent_messages_limit = _coerce_int(
            _get_value(
                data,
                ("core", "context_recent_messages_limit"),
                "CONTEXT_RECENT_MESSAGES_LIMIT",
            ),
            20,
        )
        if context_recent_messages_limit < 0:
            context_recent_messages_limit = 0
        if context_recent_messages_limit > 200:
            context_recent_messages_limit = 200

        ai_request_max_retries = _coerce_int(
            _get_value(
                data,
                ("core", "ai_request_max_retries"),
                "AI_REQUEST_MAX_RETRIES",
            ),
            2,
        )
        if ai_request_max_retries < 0:
            ai_request_max_retries = 0

        nagaagent_mode_enabled = _coerce_bool(
            _get_value(
                data,
                ("features", "nagaagent_mode_enabled"),
                "NAGAAGENT_MODE_ENABLED",
            ),
            False,
        )
        onebot_ws_url = _coerce_str(
            _get_value(data, ("onebot", "ws_url"), "ONEBOT_WS_URL"), ""
        )
        onebot_token = _coerce_str(
            _get_value(data, ("onebot", "token"), "ONEBOT_TOKEN"), ""
        )

        embedding_model = _parse_embedding_model_config(data)
        rerank_model = _parse_rerank_model_config(data)

        knowledge_enabled = _coerce_bool(
            _get_value(data, ("knowledge", "enabled"), None), False
        )
        knowledge_base_dir = _coerce_str(
            _get_value(data, ("knowledge", "base_dir"), None), "knowledge"
        )
        knowledge_auto_scan = _coerce_bool(
            _get_value(data, ("knowledge", "auto_scan"), None), False
        )
        knowledge_auto_embed = _coerce_bool(
            _get_value(data, ("knowledge", "auto_embed"), None), False
        )
        knowledge_scan_interval = _coerce_float(
            _get_value(data, ("knowledge", "scan_interval"), None), 60.0
        )
        if knowledge_scan_interval <= 0:
            knowledge_scan_interval = 60.0
        knowledge_embed_batch_size = _coerce_int(
            _get_value(data, ("knowledge", "embed_batch_size"), None), 64
        )
        if knowledge_embed_batch_size <= 0:
            knowledge_embed_batch_size = 64
        knowledge_chunk_size = _coerce_int(
            _get_value(data, ("knowledge", "chunk_size"), None), 10
        )
        if knowledge_chunk_size <= 0:
            knowledge_chunk_size = 10
        knowledge_chunk_overlap = _coerce_int(
            _get_value(data, ("knowledge", "chunk_overlap"), None), 2
        )
        if knowledge_chunk_overlap < 0:
            knowledge_chunk_overlap = 0
        knowledge_default_top_k = _coerce_int(
            _get_value(data, ("knowledge", "default_top_k"), None), 5
        )
        if knowledge_default_top_k <= 0:
            knowledge_default_top_k = 5
        knowledge_enable_rerank = _coerce_bool(
            _get_value(data, ("knowledge", "enable_rerank"), None), False
        )
        knowledge_rerank_top_k = _coerce_int(
            _get_value(data, ("knowledge", "rerank_top_k"), None), 3
        )
        if knowledge_rerank_top_k <= 0:
            knowledge_rerank_top_k = 3
        if knowledge_default_top_k <= 1 and knowledge_enable_rerank:
            logger.warning(
                "[配置] knowledge.default_top_k=%s，无法满足 rerank_top_k < default_top_k，"
                "已自动禁用重排",
                knowledge_default_top_k,
            )
            knowledge_enable_rerank = False
        if knowledge_rerank_top_k >= knowledge_default_top_k:
            fallback = knowledge_default_top_k - 1
            if fallback <= 0:
                fallback = 1
                knowledge_enable_rerank = False
                logger.warning(
                    "[配置] knowledge.rerank_top_k 需小于 knowledge.default_top_k，"
                    "且当前 default_top_k=%s 无法满足约束，已自动禁用重排",
                    knowledge_default_top_k,
                )
            else:
                logger.warning(
                    "[配置] knowledge.rerank_top_k 需小于 knowledge.default_top_k，"
                    "已回退: rerank_top_k=%s -> %s (default_top_k=%s)",
                    knowledge_rerank_top_k,
                    fallback,
                    knowledge_default_top_k,
                )
            knowledge_rerank_top_k = fallback

        chat_model = _parse_chat_model_config(data)
        vision_model = _parse_vision_model_config(data)
        security_model_enabled = _coerce_bool(
            _get_value(
                data,
                ("models", "security", "enabled"),
                "SECURITY_MODEL_ENABLED",
            ),
            True,
        )
        security_model = _parse_security_model_config(data, chat_model)
        naga_model = _parse_naga_model_config(data, security_model)
        agent_model = _parse_agent_model_config(data)
        historian_model = _parse_historian_model_config(data, agent_model)
        summary_model, summary_model_configured = _parse_summary_model_config(
            data, agent_model
        )
        grok_model = _parse_grok_model_config(data)

        model_pool_enabled = _coerce_bool(
            _get_value(data, ("features", "pool_enabled"), "MODEL_POOL_ENABLED"), False
        )

        superadmin_qq, admin_qqs = _merge_admins(
            superadmin_qq=superadmin_qq, admin_qqs=admin_qqs
        )

        access_mode_raw = _get_value(data, ("access", "mode"), "ACCESS_MODE")
        allowed_group_ids = _coerce_int_list(
            _get_value(data, ("access", "allowed_group_ids"), "ALLOWED_GROUP_IDS")
        )
        blocked_group_ids = _coerce_int_list(
            _get_value(data, ("access", "blocked_group_ids"), "BLOCKED_GROUP_IDS")
        )
        allowed_private_ids = _coerce_int_list(
            _get_value(data, ("access", "allowed_private_ids"), "ALLOWED_PRIVATE_IDS")
        )
        blocked_private_ids = _coerce_int_list(
            _get_value(data, ("access", "blocked_private_ids"), "BLOCKED_PRIVATE_IDS")
        )
        superadmin_bypass_allowlist = _coerce_bool(
            _get_value(
                data,
                ("access", "superadmin_bypass_allowlist"),
                "SUPERADMIN_BYPASS_ALLOWLIST",
            ),
            True,
        )
        superadmin_bypass_private_blacklist = _coerce_bool(
            _get_value(
                data,
                ("access", "superadmin_bypass_private_blacklist"),
                "SUPERADMIN_BYPASS_PRIVATE_BLACKLIST",
            ),
            False,
        )
        if access_mode_raw is None:
            # 兼容旧配置：未配置 mode 时沿用历史行为（群黑名单 + 白名单联动）。
            if (
                allowed_group_ids
                or blocked_group_ids
                or allowed_private_ids
                or blocked_private_ids
            ):
                access_mode = "legacy"
                logger.warning(
                    "[配置] access.mode 未设置，已启用兼容模式（legacy）。建议显式设置为 off/blacklist/allowlist。"
                )
            else:
                access_mode = "off"
        else:
            access_mode = _coerce_str(access_mode_raw, "off").lower()
            if access_mode not in {"off", "blacklist", "allowlist"}:
                logger.warning(
                    "[配置] access.mode 非法（仅支持 off/blacklist/allowlist），已回退为 off: %s",
                    access_mode,
                )
                access_mode = "off"

        log_level = _coerce_str(
            _get_value(data, ("logging", "level"), "LOG_LEVEL"), "INFO"
        ).upper()
        log_file_path = _coerce_str(
            _get_value(data, ("logging", "file_path"), "LOG_FILE_PATH"),
            "logs/bot.log",
        )
        log_max_size_mb = _coerce_int(
            _get_value(data, ("logging", "max_size_mb"), "LOG_MAX_SIZE_MB"), 10
        )
        log_backup_count = _coerce_int(
            _get_value(data, ("logging", "backup_count"), "LOG_BACKUP_COUNT"), 5
        )
        log_tty_enabled = _coerce_bool(
            _get_value(data, ("logging", "tty_enabled"), "LOG_TTY_ENABLED"),
            False,
        )
        log_thinking = _coerce_bool(
            _get_value(data, ("logging", "log_thinking"), "LOG_THINKING"), True
        )

        tools_dot_delimiter = _coerce_str(
            _get_value(data, ("tools", "dot_delimiter"), "TOOLS_DOT_DELIMITER"), "-_-"
        ).strip()
        if not tools_dot_delimiter:
            tools_dot_delimiter = "-_-"
        # dot_delimiter 必须满足 OpenAI 兼容的 function.name 约束。
        if "." in tools_dot_delimiter or not re.fullmatch(
            r"[a-zA-Z0-9_-]+", tools_dot_delimiter
        ):
            logger.warning(
                "[配置] tools.dot_delimiter 非法（仅允许 [a-zA-Z0-9_-] 且不能包含 '.'），已回退默认值: '-_-'（当前=%s）",
                tools_dot_delimiter,
            )
            tools_dot_delimiter = "-_-"
        tools_description_max_len = _coerce_int(
            _get_value(
                data, ("tools", "description_max_len"), "TOOLS_DESCRIPTION_MAX_LEN"
            ),
            1024,
        )
        tools_description_truncate_enabled = _coerce_bool(
            _get_value(
                data,
                ("tools", "description_truncate_enabled"),
                "TOOLS_DESCRIPTION_TRUNCATE_ENABLED",
            ),
            False,
        )
        tools_sanitize_verbose = _coerce_bool(
            _get_value(data, ("tools", "sanitize_verbose"), "TOOLS_SANITIZE_VERBOSE"),
            False,
        )
        tools_description_preview_len = _coerce_int(
            _get_value(
                data,
                ("tools", "description_preview_len"),
                "TOOLS_DESCRIPTION_PREVIEW_LEN",
            ),
            160,
        )

        easter_egg_mode_raw = _get_value(
            data,
            ("easter_egg", "agent_call_message_enabled"),
            "EASTER_EGG_AGENT_CALL_MESSAGE_ENABLED",
        )
        if easter_egg_mode_raw is None:
            easter_egg_mode_raw = os.getenv("EASTER_EGG_AGENT_CALL_MESSAGE_MODE")
            if easter_egg_mode_raw is not None:
                _warn_env_fallback("EASTER_EGG_AGENT_CALL_MESSAGE_MODE")
            else:
                easter_egg_mode_raw = os.getenv("EASTER_EGG_CALL_MESSAGE_MODE")
                if easter_egg_mode_raw is not None:
                    _warn_env_fallback("EASTER_EGG_CALL_MESSAGE_MODE")

        easter_egg_agent_call_message_mode = _parse_easter_egg_call_mode(
            easter_egg_mode_raw
        )

        token_usage_max_size_mb = _coerce_int(
            _get_value(data, ("token_usage", "max_size_mb"), "TOKEN_USAGE_MAX_SIZE_MB"),
            5,
        )
        token_usage_max_archives = _coerce_int(
            _get_value(
                data, ("token_usage", "max_archives"), "TOKEN_USAGE_MAX_ARCHIVES"
            ),
            30,
        )
        token_usage_max_total_mb = _coerce_int(
            _get_value(
                data, ("token_usage", "max_total_mb"), "TOKEN_USAGE_MAX_TOTAL_MB"
            ),
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

        skills_hot_reload = _coerce_bool(
            _get_value(data, ("skills", "hot_reload"), "SKILLS_HOT_RELOAD"), True
        )
        skills_hot_reload_interval = _coerce_float(
            _get_value(
                data, ("skills", "hot_reload_interval"), "SKILLS_HOT_RELOAD_INTERVAL"
            ),
            2.0,
        )
        skills_hot_reload_debounce = _coerce_float(
            _get_value(
                data, ("skills", "hot_reload_debounce"), "SKILLS_HOT_RELOAD_DEBOUNCE"
            ),
            0.5,
        )

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

        searxng_url = _coerce_str(
            _get_value(data, ("search", "searxng_url"), "SEARXNG_URL"), ""
        )
        grok_search_enabled = _coerce_bool(
            _get_value(
                data,
                ("search", "grok_search_enabled"),
                "GROK_SEARCH_ENABLED",
            ),
            False,
        )

        use_proxy = _coerce_bool(
            _get_value(data, ("proxy", "use_proxy"), "USE_PROXY"), True
        )
        http_proxy = _coerce_str(
            _get_value(data, ("proxy", "http_proxy"), "http_proxy"), ""
        )
        if not http_proxy:
            http_proxy = _coerce_str(os.getenv("HTTP_PROXY"), "")
            if http_proxy:
                _warn_env_fallback("HTTP_PROXY")
        https_proxy = _coerce_str(
            _get_value(data, ("proxy", "https_proxy"), "https_proxy"), ""
        )
        if not https_proxy:
            https_proxy = _coerce_str(os.getenv("HTTPS_PROXY"), "")
            if https_proxy:
                _warn_env_fallback("HTTPS_PROXY")

        network_request_timeout = _coerce_float(
            _get_value(
                data,
                ("network", "request_timeout_seconds"),
                "NETWORK_REQUEST_TIMEOUT_SECONDS",
            ),
            30.0,
        )
        if network_request_timeout <= 0:
            network_request_timeout = 480.0

        network_request_retries = _coerce_int(
            _get_value(
                data,
                ("network", "request_retries"),
                "NETWORK_REQUEST_RETRIES",
            ),
            0,
        )
        if network_request_retries < 0:
            network_request_retries = 0
        if network_request_retries > 5:
            network_request_retries = 5

        api_xxapi_base_url = _normalize_base_url(
            _coerce_str(
                _get_value(data, ("api_endpoints", "xxapi_base_url"), "XXAPI_BASE_URL"),
                "https://v2.xxapi.cn",
            ),
            "https://v2.xxapi.cn",
        )
        api_xingzhige_base_url = _normalize_base_url(
            _coerce_str(
                _get_value(
                    data,
                    ("api_endpoints", "xingzhige_base_url"),
                    "XINGZHIGE_BASE_URL",
                ),
                "https://api.xingzhige.com",
            ),
            "https://api.xingzhige.com",
        )
        api_jkyai_base_url = _normalize_base_url(
            _coerce_str(
                _get_value(data, ("api_endpoints", "jkyai_base_url"), "JKYAI_BASE_URL"),
                "https://api.jkyai.top",
            ),
            "https://api.jkyai.top",
        )
        api_seniverse_base_url = _normalize_base_url(
            _coerce_str(
                _get_value(
                    data,
                    ("api_endpoints", "seniverse_base_url"),
                    "SENIVERSE_BASE_URL",
                ),
                "https://api.seniverse.com/v3",
            ),
            "https://api.seniverse.com/v3",
        )

        weather_api_key = _coerce_str(
            _get_value(data, ("weather", "api_key"), "WEATHER_API_KEY"), ""
        )
        xxapi_api_token = _coerce_str(
            _get_value(data, ("xxapi", "api_token"), "XXAPI_API_TOKEN"), ""
        )

        mcp_config_path = _coerce_str(
            _get_value(data, ("mcp", "config_path"), "MCP_CONFIG_PATH"),
            "config/mcp.json",
        )

        # Bilibili 配置
        bilibili_auto_extract_enabled = _coerce_bool(
            _get_value(data, ("bilibili", "auto_extract_enabled"), None), False
        )
        bilibili_cookie = _coerce_str(
            _get_value(data, ("bilibili", "cookie"), None), ""
        )
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
        bilibili_auto_extract_group_ids = _coerce_int_list(
            _get_value(data, ("bilibili", "auto_extract_group_ids"), None)
        )
        bilibili_auto_extract_private_ids = _coerce_int_list(
            _get_value(data, ("bilibili", "auto_extract_private_ids"), None)
        )

        # arXiv 配置
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
            _get_value(
                data, ("code_delivery", "default_command_timeout_seconds"), None
            ),
            600,
        )
        code_delivery_max_command_output = _coerce_int(
            _get_value(data, ("code_delivery", "max_command_output_chars"), None),
            20000,
        )
        code_delivery_default_archive_format = _coerce_str(
            _get_value(data, ("code_delivery", "default_archive_format"), None),
            "zip",
        )
        if code_delivery_default_archive_format not in ("zip", "tar.gz"):
            code_delivery_default_archive_format = "zip"
        code_delivery_max_archive_size_mb = _coerce_int(
            _get_value(data, ("code_delivery", "max_archive_size_mb"), None), 200
        )
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
        else:
            code_delivery_command_blacklist = []

        # messages 工具集配置
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

        webui_settings = load_webui_settings(config_path)
        api_config = _parse_api_config(data)

        cognitive = _parse_cognitive_config(data)
        memes = _parse_memes_config(data)
        naga = _parse_naga_config(data)
        models_image_gen = _parse_image_gen_model_config(data)
        models_image_edit = _parse_image_edit_model_config(data)
        image_gen = _parse_image_gen_config(data)

        if strict:
            _verify_required_fields(
                bot_qq=bot_qq,
                superadmin_qq=superadmin_qq,
                onebot_ws_url=onebot_ws_url,
                chat_model=chat_model,
                vision_model=vision_model,
                agent_model=agent_model,
                knowledge_enabled=knowledge_enabled,
                embedding_model=embedding_model,
            )

        _log_debug_info(
            chat_model,
            vision_model,
            security_model,
            naga_model,
            agent_model,
            summary_model,
            grok_model,
        )

        return cls(
            bot_qq=bot_qq,
            superadmin_qq=superadmin_qq,
            admin_qqs=admin_qqs,
            access_mode=access_mode,
            allowed_group_ids=allowed_group_ids,
            blocked_group_ids=blocked_group_ids,
            allowed_private_ids=allowed_private_ids,
            blocked_private_ids=blocked_private_ids,
            superadmin_bypass_allowlist=superadmin_bypass_allowlist,
            superadmin_bypass_private_blacklist=superadmin_bypass_private_blacklist,
            forward_proxy_qq=forward_proxy_qq,
            process_every_message=process_every_message,
            process_private_message=process_private_message,
            process_poke_message=process_poke_message,
            keyword_reply_enabled=keyword_reply_enabled,
            repeat_enabled=repeat_enabled,
            repeat_threshold=repeat_threshold,
            repeat_cooldown_minutes=repeat_cooldown_minutes,
            inverted_question_enabled=inverted_question_enabled,
            context_recent_messages_limit=context_recent_messages_limit,
            ai_request_max_retries=ai_request_max_retries,
            nagaagent_mode_enabled=nagaagent_mode_enabled,
            onebot_ws_url=onebot_ws_url,
            onebot_token=onebot_token,
            chat_model=chat_model,
            vision_model=vision_model,
            security_model_enabled=security_model_enabled,
            security_model=security_model,
            naga_model=naga_model,
            agent_model=agent_model,
            historian_model=historian_model,
            summary_model=summary_model,
            summary_model_configured=summary_model_configured,
            grok_model=grok_model,
            model_pool_enabled=model_pool_enabled,
            log_level=log_level,
            log_file_path=log_file_path,
            log_max_size=log_max_size_mb * 1024 * 1024,
            log_backup_count=log_backup_count,
            log_tty_enabled=log_tty_enabled,
            log_thinking=log_thinking,
            tools_dot_delimiter=tools_dot_delimiter,
            tools_description_truncate_enabled=tools_description_truncate_enabled,
            tools_description_max_len=tools_description_max_len,
            tools_sanitize_verbose=tools_sanitize_verbose,
            tools_description_preview_len=tools_description_preview_len,
            easter_egg_agent_call_message_mode=easter_egg_agent_call_message_mode,
            token_usage_max_size_mb=token_usage_max_size_mb,
            token_usage_max_archives=token_usage_max_archives,
            token_usage_max_total_mb=token_usage_max_total_mb,
            token_usage_archive_prune_mode=token_usage_archive_prune_mode,
            skills_hot_reload=skills_hot_reload,
            history_max_records=history_max_records,
            history_filtered_result_limit=history_filtered_result_limit,
            history_search_scan_limit=history_search_scan_limit,
            history_summary_fetch_limit=history_summary_fetch_limit,
            history_summary_time_fetch_limit=history_summary_time_fetch_limit,
            history_onebot_fetch_limit=history_onebot_fetch_limit,
            history_group_analysis_limit=history_group_analysis_limit,
            skills_hot_reload_interval=skills_hot_reload_interval,
            skills_hot_reload_debounce=skills_hot_reload_debounce,
            agent_intro_autogen_enabled=agent_intro_autogen_enabled,
            agent_intro_autogen_queue_interval=agent_intro_autogen_queue_interval,
            agent_intro_autogen_max_tokens=agent_intro_autogen_max_tokens,
            agent_intro_hash_path=agent_intro_hash_path,
            searxng_url=searxng_url,
            grok_search_enabled=grok_search_enabled,
            use_proxy=use_proxy,
            http_proxy=http_proxy,
            https_proxy=https_proxy,
            network_request_timeout=network_request_timeout,
            network_request_retries=network_request_retries,
            api_xxapi_base_url=api_xxapi_base_url,
            api_xingzhige_base_url=api_xingzhige_base_url,
            api_jkyai_base_url=api_jkyai_base_url,
            api_seniverse_base_url=api_seniverse_base_url,
            weather_api_key=weather_api_key,
            xxapi_api_token=xxapi_api_token,
            mcp_config_path=mcp_config_path,
            prefetch_tools=prefetch_tools,
            prefetch_tools_hide=prefetch_tools_hide,
            webui_url=webui_settings.url,
            webui_port=webui_settings.port,
            webui_password=webui_settings.password,
            api=api_config,
            code_delivery_enabled=code_delivery_enabled,
            code_delivery_task_root=code_delivery_task_root,
            code_delivery_docker_image=code_delivery_docker_image,
            code_delivery_container_name_prefix=code_delivery_container_name_prefix,
            code_delivery_container_name_suffix=code_delivery_container_name_suffix,
            code_delivery_command_timeout=code_delivery_command_timeout,
            code_delivery_max_command_output=code_delivery_max_command_output,
            code_delivery_default_archive_format=code_delivery_default_archive_format,
            code_delivery_max_archive_size_mb=code_delivery_max_archive_size_mb,
            code_delivery_cleanup_on_finish=code_delivery_cleanup_on_finish,
            code_delivery_cleanup_on_start=code_delivery_cleanup_on_start,
            code_delivery_llm_max_retries=code_delivery_llm_max_retries,
            code_delivery_notify_on_llm_failure=code_delivery_notify_on_llm_failure,
            code_delivery_container_memory_limit=code_delivery_container_memory_limit,
            code_delivery_container_cpu_limit=code_delivery_container_cpu_limit,
            code_delivery_command_blacklist=code_delivery_command_blacklist,
            messages_send_text_file_max_size_kb=messages_send_text_file_max_size_kb,
            messages_send_url_file_max_size_mb=messages_send_url_file_max_size_mb,
            bilibili_auto_extract_enabled=bilibili_auto_extract_enabled,
            bilibili_cookie=bilibili_cookie,
            bilibili_prefer_quality=bilibili_prefer_quality,
            bilibili_max_duration=bilibili_max_duration,
            bilibili_max_file_size=bilibili_max_file_size,
            bilibili_oversize_strategy=bilibili_oversize_strategy,
            bilibili_auto_extract_group_ids=bilibili_auto_extract_group_ids,
            bilibili_auto_extract_private_ids=bilibili_auto_extract_private_ids,
            arxiv_auto_extract_enabled=arxiv_auto_extract_enabled,
            arxiv_max_file_size=arxiv_max_file_size,
            arxiv_auto_extract_group_ids=arxiv_auto_extract_group_ids,
            arxiv_auto_extract_private_ids=arxiv_auto_extract_private_ids,
            arxiv_auto_extract_max_items=arxiv_auto_extract_max_items,
            arxiv_author_preview_limit=arxiv_author_preview_limit,
            arxiv_summary_preview_chars=arxiv_summary_preview_chars,
            embedding_model=embedding_model,
            rerank_model=rerank_model,
            knowledge_enabled=knowledge_enabled,
            knowledge_base_dir=knowledge_base_dir,
            knowledge_auto_scan=knowledge_auto_scan,
            knowledge_auto_embed=knowledge_auto_embed,
            knowledge_scan_interval=knowledge_scan_interval,
            knowledge_embed_batch_size=knowledge_embed_batch_size,
            knowledge_chunk_size=knowledge_chunk_size,
            knowledge_chunk_overlap=knowledge_chunk_overlap,
            knowledge_default_top_k=knowledge_default_top_k,
            knowledge_enable_rerank=knowledge_enable_rerank,
            knowledge_rerank_top_k=knowledge_rerank_top_k,
            cognitive=cognitive,
            memes=memes,
            naga=naga,
            image_gen=image_gen,
            models_image_gen=models_image_gen,
            models_image_edit=models_image_edit,
        )

    @property
    def bilibili_sessdata(self) -> str:
        """兼容旧字段名，等价于 bilibili_cookie。"""
        return self.bilibili_cookie

    def allowlist_mode_enabled(self) -> bool:
        """是否启用白名单限制模式。"""

        return self.access_mode in {"allowlist", "legacy"} and (
            bool(self.allowed_group_ids) or bool(self.allowed_private_ids)
        )

    def group_allowlist_enabled(self) -> bool:
        """群聊白名单是否生效（显式 allowlist 模式按维度独立控制）。"""

        return bool(self.allowed_group_ids)

    def private_allowlist_enabled(self) -> bool:
        """私聊白名单是否生效（显式 allowlist 模式按维度独立控制）。"""

        return bool(self.allowed_private_ids)

    def blacklist_mode_enabled(self) -> bool:
        """是否启用黑名单限制模式。"""

        return self.access_mode in {"blacklist", "legacy"} and (
            bool(self.blocked_group_ids) or bool(self.blocked_private_ids)
        )

    def access_control_enabled(self) -> bool:
        """是否启用访问控制。"""

        return self.allowlist_mode_enabled() or self.blacklist_mode_enabled()

    def group_access_denied_reason(self, group_id: int) -> str | None:
        """群聊访问被拒绝原因。

        返回:
            - "blacklist": 命中 access.blocked_group_ids
            - "allowlist": allowlist 模式下不在 access.allowed_group_ids
            - None: 允许访问
        """

        normalized_group_id = int(group_id)
        if self.access_mode == "off":
            return None
        if self.access_mode == "blacklist":
            if normalized_group_id in self._blocked_group_ids_set:
                return "blacklist"
            return None
        if self.access_mode == "legacy":
            if normalized_group_id in self._blocked_group_ids_set:
                return "blacklist"
            if not self.allowlist_mode_enabled():
                return None
            if normalized_group_id not in self._allowed_group_ids_set:
                return "allowlist"
            return None
        if not self.group_allowlist_enabled():
            return None
        if normalized_group_id not in self._allowed_group_ids_set:
            return "allowlist"
        return None

    def is_group_allowed(self, group_id: int) -> bool:
        """群聊是否允许收发消息。"""

        return self.group_access_denied_reason(group_id) is None

    def private_access_denied_reason(self, user_id: int) -> str | None:
        """私聊访问被拒绝原因。"""

        normalized_user_id = int(user_id)
        if self.access_mode == "off":
            return None
        if self.access_mode == "blacklist":
            if normalized_user_id not in self._blocked_private_ids_set:
                return None
            if (
                self.superadmin_bypass_private_blacklist
                and normalized_user_id == int(self.superadmin_qq)
                and self.superadmin_qq > 0
            ):
                return None
            return "blacklist"
        if self.access_mode == "legacy":
            if normalized_user_id in self._blocked_private_ids_set:
                if (
                    self.superadmin_bypass_private_blacklist
                    and normalized_user_id == int(self.superadmin_qq)
                    and self.superadmin_qq > 0
                ):
                    return None
                return "blacklist"
            if not self.allowlist_mode_enabled():
                return None
            if (
                self.superadmin_bypass_allowlist
                and normalized_user_id == int(self.superadmin_qq)
                and self.superadmin_qq > 0
            ):
                return None
            if normalized_user_id not in self._allowed_private_ids_set:
                return "allowlist"
            return None
        if not self.private_allowlist_enabled():
            return None
        if (
            self.superadmin_bypass_allowlist
            and normalized_user_id == int(self.superadmin_qq)
            and self.superadmin_qq > 0
        ):
            return None
        if normalized_user_id not in self._allowed_private_ids_set:
            return "allowlist"
        return None

    def is_private_allowed(self, user_id: int) -> bool:
        """私聊是否允许收发消息。"""

        return self.private_access_denied_reason(user_id) is None

    def is_bilibili_auto_extract_allowed_group(self, group_id: int) -> bool:
        """群聊是否允许 bilibili 自动提取。"""
        if self._bilibili_group_ids_set:
            return int(group_id) in self._bilibili_group_ids_set
        # 功能白名单为空时跟随全局 access 控制
        return self.is_group_allowed(group_id)

    def is_bilibili_auto_extract_allowed_private(self, user_id: int) -> bool:
        """私聊是否允许 bilibili 自动提取。"""
        if self._bilibili_private_ids_set:
            return int(user_id) in self._bilibili_private_ids_set
        # 功能白名单为空时跟随全局 access 控制
        return self.is_private_allowed(user_id)

    def is_arxiv_auto_extract_allowed_group(self, group_id: int) -> bool:
        """群聊是否允许 arXiv 自动提取。"""
        if self._arxiv_group_ids_set:
            return int(group_id) in self._arxiv_group_ids_set
        return self.is_group_allowed(group_id)

    def is_arxiv_auto_extract_allowed_private(self, user_id: int) -> bool:
        """私聊是否允许 arXiv 自动提取。"""
        if self._arxiv_private_ids_set:
            return int(user_id) in self._arxiv_private_ids_set
        return self.is_private_allowed(user_id)

    def should_process_group_message(self, is_at_bot: bool) -> bool:
        """是否处理该条群消息。"""

        if self.process_every_message:
            return True
        return bool(is_at_bot)

    def should_process_private_message(self) -> bool:
        """是否处理私聊消息回复。"""

        return bool(self.process_private_message)

    def should_process_poke_message(self) -> bool:
        """是否处理拍一拍触发。"""

        return bool(self.process_poke_message)

    def get_context_recent_messages_limit(self) -> int:
        """获取上下文最近历史消息条数上限。"""

        limit = int(self.context_recent_messages_limit)
        if limit < 0:
            return 0
        if limit > 200:
            return 200
        return limit

    def security_check_enabled(self) -> bool:
        """是否启用安全模型检查。"""

        return bool(self.security_model_enabled)

    def update_from(self, new_config: "Config") -> dict[str, tuple[Any, Any]]:
        changes: dict[str, tuple[Any, Any]] = {}
        for field in fields(self):
            name = field.name
            old_value = getattr(self, name)
            new_value = getattr(new_config, name)
            if isinstance(
                old_value,
                (
                    ChatModelConfig,
                    VisionModelConfig,
                    SecurityModelConfig,
                    AgentModelConfig,
                    GrokModelConfig,
                ),
            ):
                changes.update(_update_dataclass(old_value, new_value, prefix=name))
                continue
            if old_value != new_value:
                setattr(self, name, new_value)
                changes[name] = (old_value, new_value)
        return changes

    def reload(self, strict: bool = False) -> dict[str, tuple[Any, Any]]:
        new_config = Config.load(strict=strict)
        return self.update_from(new_config)

    def add_admin(self, qq: int) -> bool:
        if qq in self.admin_qqs:
            return False
        self.admin_qqs.append(qq)
        local_admins = load_local_admins()
        if qq not in local_admins:
            local_admins.append(qq)
            save_local_admins(local_admins)
        return True

    def remove_admin(self, qq: int) -> bool:
        if qq == self.superadmin_qq or qq not in self.admin_qqs:
            return False
        self.admin_qqs.remove(qq)
        local_admins = load_local_admins()
        if qq in local_admins:
            local_admins.remove(qq)
            save_local_admins(local_admins)
        return True

    def is_superadmin(self, qq: int) -> bool:
        return qq == self.superadmin_qq

    def is_admin(self, qq: int) -> bool:
        return qq in self.admin_qqs
