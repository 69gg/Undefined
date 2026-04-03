"""配置加载逻辑"""

from __future__ import annotations

import json
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
    ModelPool,
    ModelPoolEntry,
    NagaConfig,
    RerankModelConfig,
    SecurityModelConfig,
    VisionModelConfig,
)
from Undefined.utils.request_params import (
    merge_request_params,
    normalize_request_params,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.toml")
LOCAL_CONFIG_PATH = Path("config.local.json")

DEFAULT_WEBUI_URL = "127.0.0.1"
DEFAULT_WEBUI_PORT = 8787
DEFAULT_WEBUI_PASSWORD = "changeme"
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8788
DEFAULT_API_AUTH_KEY = "changeme"

_ENV_WARNED_KEYS: set[str] = set()


def _warn_env_fallback(name: str) -> None:
    if name in _ENV_WARNED_KEYS:
        return
    _ENV_WARNED_KEYS.add(name)
    logger.warning("检测到环境变量 %s，建议迁移到 config.toml", name)


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


def _get_nested(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _normalize_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return str(value).strip()


def _coerce_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_queue_interval(value: float, default: float = 1.0) -> float:
    """规范化队列发车间隔。

    `0` 表示立即发车，负数回退到默认值。
    """

    return default if value < 0 else value


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _coerce_str(value: Any, default: str) -> str:
    normalized = _normalize_str(value)
    return normalized if normalized is not None else default


def _normalize_base_url(value: str, default: str) -> str:
    normalized = value.strip().rstrip("/")
    if normalized:
        return normalized
    return default.rstrip("/")


def _coerce_int_list(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        items: list[int] = []
        for item in value:
            try:
                items.append(int(item))
            except (TypeError, ValueError):
                continue
        return items
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
        items = []
        for part in parts:
            try:
                items.append(int(part))
            except ValueError:
                continue
        return items
    return []


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _coerce_request_params(value: Any) -> dict[str, Any]:
    return normalize_request_params(value)


def _get_model_request_params(data: dict[str, Any], model_name: str) -> dict[str, Any]:
    return _coerce_request_params(
        _get_nested(data, ("models", model_name, "request_params"))
    )


def _get_value(
    data: dict[str, Any],
    path: tuple[str, ...],
    env_key: Optional[str],
) -> Any:
    value = _get_nested(data, path)
    if value is not None:
        return value
    if env_key:
        env_value = os.getenv(env_key)
        if env_value is not None and str(env_value).strip() != "":
            _warn_env_fallback(env_key)
            return env_value
    return None


_VALID_API_MODES = {"chat_completions", "responses"}
_VALID_REASONING_EFFORT_STYLES = {"openai", "anthropic"}


def _resolve_reasoning_effort_style(value: Any, default: str = "openai") -> str:
    style = _coerce_str(value, default).strip().lower()
    if style not in _VALID_REASONING_EFFORT_STYLES:
        return default
    return style


def _resolve_thinking_compat_flags(
    data: dict[str, Any],
    model_name: str,
    include_budget_env_key: str,
    tool_call_compat_env_key: str,
    legacy_env_key: str,
) -> tuple[bool, bool]:
    """解析思维链兼容配置，并兼容旧字段 deepseek_new_cot_support。"""
    include_budget_value = _get_value(
        data,
        ("models", model_name, "thinking_include_budget"),
        include_budget_env_key,
    )
    tool_call_compat_value = _get_value(
        data,
        ("models", model_name, "thinking_tool_call_compat"),
        tool_call_compat_env_key,
    )
    legacy_value = _get_value(
        data,
        ("models", model_name, "deepseek_new_cot_support"),
        legacy_env_key,
    )

    include_budget_default = True
    tool_call_compat_default = True
    if legacy_value is not None:
        legacy_enabled = _coerce_bool(legacy_value, False)
        include_budget_default = not legacy_enabled
        tool_call_compat_default = legacy_enabled

    return (
        _coerce_bool(include_budget_value, include_budget_default),
        _coerce_bool(tool_call_compat_value, tool_call_compat_default),
    )


def _resolve_api_mode(
    data: dict[str, Any],
    model_name: str,
    env_key: str,
    default: str = "chat_completions",
) -> str:
    raw_value = _get_value(data, ("models", model_name, "api_mode"), env_key)
    value = _coerce_str(raw_value, default).strip().lower()
    if value not in _VALID_API_MODES:
        return default
    return value


def _resolve_reasoning_effort(value: Any, default: str = "medium") -> str:
    return _coerce_str(value, default).strip().lower()


def _resolve_responses_tool_choice_compat(
    data: dict[str, Any],
    model_name: str,
    env_key: str,
    default: bool = False,
) -> bool:
    return _coerce_bool(
        _get_value(
            data,
            ("models", model_name, "responses_tool_choice_compat"),
            env_key,
        ),
        default,
    )


def _resolve_responses_force_stateless_replay(
    data: dict[str, Any],
    model_name: str,
    env_key: str,
    default: bool = False,
) -> bool:
    return _coerce_bool(
        _get_value(
            data,
            ("models", model_name, "responses_force_stateless_replay"),
            env_key,
        ),
        default,
    )


def load_local_admins() -> list[int]:
    """从本地配置文件加载动态管理员列表"""
    if not LOCAL_CONFIG_PATH.exists():
        return []
    try:
        with open(LOCAL_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        admin_qqs: list[int] = data.get("admin_qqs", [])
        return admin_qqs
    except Exception as exc:
        logger.warning("读取本地配置失败: %s", exc)
        return []


def save_local_admins(admin_qqs: list[int]) -> None:
    """保存动态管理员列表到本地配置文件"""
    try:
        data: dict[str, list[int]] = {}
        if LOCAL_CONFIG_PATH.exists():
            with open(LOCAL_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

        data["admin_qqs"] = admin_qqs

        with open(LOCAL_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info("已保存管理员列表到 %s", LOCAL_CONFIG_PATH)
    except Exception as exc:
        logger.error("保存本地配置失败: %s", exc)
        raise


@dataclass
class WebUISettings:
    url: str
    port: int
    password: str
    using_default_password: bool
    config_exists: bool

    @property
    def display_url(self) -> str:
        """用于日志和展示的格式化 URL。"""
        from Undefined.config.models import format_netloc

        return f"http://{format_netloc(self.url or '0.0.0.0', self.port)}"


def load_webui_settings(config_path: Optional[Path] = None) -> WebUISettings:
    data = load_toml_data(config_path)
    config_exists = bool(data)
    url_value = _get_value(data, ("webui", "url"), None)
    port_value = _get_value(data, ("webui", "port"), None)
    password_value = _get_value(data, ("webui", "password"), None)

    url = _coerce_str(url_value, DEFAULT_WEBUI_URL)
    port = _coerce_int(port_value, DEFAULT_WEBUI_PORT)
    if port <= 0 or port > 65535:
        port = DEFAULT_WEBUI_PORT

    password_normalized = _normalize_str(password_value)
    if not password_normalized:
        return WebUISettings(
            url=url,
            port=port,
            password=DEFAULT_WEBUI_PASSWORD,
            using_default_password=True,
            config_exists=config_exists,
        )
    return WebUISettings(
        url=url,
        port=port,
        password=password_normalized,
        using_default_password=False,
        config_exists=config_exists,
    )


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

        embedding_model = cls._parse_embedding_model_config(data)
        rerank_model = cls._parse_rerank_model_config(data)

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

        chat_model = cls._parse_chat_model_config(data)
        vision_model = cls._parse_vision_model_config(data)
        security_model_enabled = _coerce_bool(
            _get_value(
                data,
                ("models", "security", "enabled"),
                "SECURITY_MODEL_ENABLED",
            ),
            True,
        )
        security_model = cls._parse_security_model_config(data, chat_model)
        naga_model = cls._parse_naga_model_config(data, security_model)
        agent_model = cls._parse_agent_model_config(data)
        historian_model = cls._parse_historian_model_config(data, agent_model)
        grok_model = cls._parse_grok_model_config(data)

        model_pool_enabled = _coerce_bool(
            _get_value(data, ("features", "pool_enabled"), "MODEL_POOL_ENABLED"), False
        )

        superadmin_qq, admin_qqs = cls._merge_admins(
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

        easter_egg_agent_call_message_mode = cls._parse_easter_egg_call_mode(
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

        history_max_records = _coerce_int(
            _get_value(data, ("history", "max_records"), "HISTORY_MAX_RECORDS"), 10000
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
        api_config = cls._parse_api_config(data)

        cognitive = cls._parse_cognitive_config(data)
        memes = cls._parse_memes_config(data)
        naga = cls._parse_naga_config(data)
        models_image_gen = cls._parse_image_gen_model_config(data)
        models_image_edit = cls._parse_image_edit_model_config(data)
        image_gen = cls._parse_image_gen_config(data)

        if strict:
            cls._verify_required_fields(
                bot_qq=bot_qq,
                superadmin_qq=superadmin_qq,
                onebot_ws_url=onebot_ws_url,
                chat_model=chat_model,
                vision_model=vision_model,
                agent_model=agent_model,
                knowledge_enabled=knowledge_enabled,
                embedding_model=embedding_model,
            )

        cls._log_debug_info(
            chat_model,
            vision_model,
            security_model,
            naga_model,
            agent_model,
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

    @staticmethod
    def _parse_model_pool(
        data: dict[str, Any],
        model_section: str,
        primary_config: ChatModelConfig | AgentModelConfig,
    ) -> ModelPool | None:
        """解析模型池配置，缺省字段继承 primary_config"""
        pool_data = data.get("models", {}).get(model_section, {}).get("pool")
        if not isinstance(pool_data, dict):
            return None

        enabled = _coerce_bool(pool_data.get("enabled"), False)
        strategy = _coerce_str(pool_data.get("strategy"), "default").strip().lower()
        if strategy not in ("default", "round_robin", "random"):
            strategy = "default"

        raw_models = pool_data.get("models")
        if not isinstance(raw_models, list):
            return ModelPool(enabled=enabled, strategy=strategy)

        entries: list[ModelPoolEntry] = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            name = _coerce_str(item.get("model_name"), "").strip()
            if not name:
                continue
            entries.append(
                ModelPoolEntry(
                    api_url=_coerce_str(item.get("api_url"), primary_config.api_url),
                    api_key=_coerce_str(item.get("api_key"), primary_config.api_key),
                    model_name=name,
                    max_tokens=_coerce_int(
                        item.get("max_tokens"), primary_config.max_tokens
                    ),
                    queue_interval_seconds=_normalize_queue_interval(
                        _coerce_float(
                            item.get("queue_interval_seconds"),
                            primary_config.queue_interval_seconds,
                        ),
                        primary_config.queue_interval_seconds,
                    ),
                    api_mode=(
                        _coerce_str(item.get("api_mode"), primary_config.api_mode)
                        .strip()
                        .lower()
                    )
                    if _coerce_str(item.get("api_mode"), primary_config.api_mode)
                    .strip()
                    .lower()
                    in _VALID_API_MODES
                    else primary_config.api_mode,
                    thinking_enabled=_coerce_bool(
                        item.get("thinking_enabled"), primary_config.thinking_enabled
                    ),
                    thinking_budget_tokens=_coerce_int(
                        item.get("thinking_budget_tokens"),
                        primary_config.thinking_budget_tokens,
                    ),
                    thinking_include_budget=_coerce_bool(
                        item.get("thinking_include_budget"),
                        primary_config.thinking_include_budget,
                    ),
                    reasoning_effort_style=_resolve_reasoning_effort_style(
                        item.get("reasoning_effort_style"),
                        primary_config.reasoning_effort_style,
                    ),
                    thinking_tool_call_compat=_coerce_bool(
                        item.get("thinking_tool_call_compat"),
                        primary_config.thinking_tool_call_compat,
                    ),
                    responses_tool_choice_compat=_coerce_bool(
                        item.get("responses_tool_choice_compat"),
                        primary_config.responses_tool_choice_compat,
                    ),
                    responses_force_stateless_replay=_coerce_bool(
                        item.get("responses_force_stateless_replay"),
                        primary_config.responses_force_stateless_replay,
                    ),
                    reasoning_enabled=_coerce_bool(
                        item.get("reasoning_enabled"),
                        primary_config.reasoning_enabled,
                    ),
                    reasoning_effort=_resolve_reasoning_effort(
                        item.get("reasoning_effort"),
                        primary_config.reasoning_effort,
                    ),
                    request_params=merge_request_params(
                        primary_config.request_params,
                        item.get("request_params"),
                    ),
                )
            )

        return ModelPool(enabled=enabled, strategy=strategy, models=entries)

    @staticmethod
    def _parse_embedding_model_config(data: dict[str, Any]) -> EmbeddingModelConfig:
        return EmbeddingModelConfig(
            api_url=_coerce_str(
                _get_value(
                    data, ("models", "embedding", "api_url"), "EMBEDDING_MODEL_API_URL"
                ),
                "",
            ),
            api_key=_coerce_str(
                _get_value(
                    data, ("models", "embedding", "api_key"), "EMBEDDING_MODEL_API_KEY"
                ),
                "",
            ),
            model_name=_coerce_str(
                _get_value(
                    data, ("models", "embedding", "model_name"), "EMBEDDING_MODEL_NAME"
                ),
                "",
            ),
            queue_interval_seconds=_normalize_queue_interval(
                _coerce_float(
                    _get_value(
                        data, ("models", "embedding", "queue_interval_seconds"), None
                    ),
                    0.0,
                ),
                0.0,
            ),
            dimensions=_coerce_int(
                _get_value(data, ("models", "embedding", "dimensions"), None), 0
            )
            or None,
            query_instruction=_coerce_str(
                _get_value(data, ("models", "embedding", "query_instruction"), None), ""
            ),
            document_instruction=_coerce_str(
                _get_value(data, ("models", "embedding", "document_instruction"), None),
                "",
            ),
            request_params=_get_model_request_params(data, "embedding"),
        )

    @staticmethod
    def _parse_rerank_model_config(data: dict[str, Any]) -> RerankModelConfig:
        queue_interval_seconds = _normalize_queue_interval(
            _coerce_float(
                _get_value(data, ("models", "rerank", "queue_interval_seconds"), None),
                0.0,
            ),
            0.0,
        )
        return RerankModelConfig(
            api_url=_coerce_str(
                _get_value(
                    data, ("models", "rerank", "api_url"), "RERANK_MODEL_API_URL"
                ),
                "",
            ),
            api_key=_coerce_str(
                _get_value(
                    data, ("models", "rerank", "api_key"), "RERANK_MODEL_API_KEY"
                ),
                "",
            ),
            model_name=_coerce_str(
                _get_value(
                    data, ("models", "rerank", "model_name"), "RERANK_MODEL_NAME"
                ),
                "",
            ),
            queue_interval_seconds=queue_interval_seconds,
            query_instruction=_coerce_str(
                _get_value(data, ("models", "rerank", "query_instruction"), None), ""
            ),
            request_params=_get_model_request_params(data, "rerank"),
        )

    @staticmethod
    def _parse_chat_model_config(data: dict[str, Any]) -> ChatModelConfig:
        queue_interval_seconds = _normalize_queue_interval(
            _coerce_float(
                _get_value(
                    data,
                    ("models", "chat", "queue_interval_seconds"),
                    "CHAT_MODEL_QUEUE_INTERVAL",
                ),
                1.0,
            )
        )
        thinking_include_budget, thinking_tool_call_compat = (
            _resolve_thinking_compat_flags(
                data=data,
                model_name="chat",
                include_budget_env_key="CHAT_MODEL_THINKING_INCLUDE_BUDGET",
                tool_call_compat_env_key="CHAT_MODEL_THINKING_TOOL_CALL_COMPAT",
                legacy_env_key="CHAT_MODEL_DEEPSEEK_NEW_COT_SUPPORT",
            )
        )
        api_mode = _resolve_api_mode(data, "chat", "CHAT_MODEL_API_MODE")
        responses_tool_choice_compat = _resolve_responses_tool_choice_compat(
            data, "chat", "CHAT_MODEL_RESPONSES_TOOL_CHOICE_COMPAT"
        )
        responses_force_stateless_replay = _resolve_responses_force_stateless_replay(
            data, "chat", "CHAT_MODEL_RESPONSES_FORCE_STATELESS_REPLAY"
        )
        reasoning_enabled = _coerce_bool(
            _get_value(
                data,
                ("models", "chat", "reasoning_enabled"),
                "CHAT_MODEL_REASONING_ENABLED",
            ),
            False,
        )
        reasoning_effort = _resolve_reasoning_effort(
            _get_value(
                data,
                ("models", "chat", "reasoning_effort"),
                "CHAT_MODEL_REASONING_EFFORT",
            ),
            "medium",
        )
        config = ChatModelConfig(
            api_url=_coerce_str(
                _get_value(data, ("models", "chat", "api_url"), "CHAT_MODEL_API_URL"),
                "",
            ),
            api_key=_coerce_str(
                _get_value(data, ("models", "chat", "api_key"), "CHAT_MODEL_API_KEY"),
                "",
            ),
            model_name=_coerce_str(
                _get_value(data, ("models", "chat", "model_name"), "CHAT_MODEL_NAME"),
                "",
            ),
            max_tokens=_coerce_int(
                _get_value(
                    data, ("models", "chat", "max_tokens"), "CHAT_MODEL_MAX_TOKENS"
                ),
                8192,
            ),
            queue_interval_seconds=queue_interval_seconds,
            api_mode=api_mode,
            thinking_enabled=_coerce_bool(
                _get_value(
                    data,
                    ("models", "chat", "thinking_enabled"),
                    "CHAT_MODEL_THINKING_ENABLED",
                ),
                False,
            ),
            thinking_budget_tokens=_coerce_int(
                _get_value(
                    data,
                    ("models", "chat", "thinking_budget_tokens"),
                    "CHAT_MODEL_THINKING_BUDGET_TOKENS",
                ),
                20000,
            ),
            thinking_include_budget=thinking_include_budget,
            reasoning_effort_style=_resolve_reasoning_effort_style(
                _get_value(
                    data,
                    ("models", "chat", "reasoning_effort_style"),
                    "CHAT_MODEL_REASONING_EFFORT_STYLE",
                ),
            ),
            thinking_tool_call_compat=thinking_tool_call_compat,
            responses_tool_choice_compat=responses_tool_choice_compat,
            responses_force_stateless_replay=responses_force_stateless_replay,
            reasoning_enabled=reasoning_enabled,
            reasoning_effort=reasoning_effort,
            request_params=_get_model_request_params(data, "chat"),
        )
        config.pool = Config._parse_model_pool(data, "chat", config)
        return config

    @staticmethod
    def _parse_vision_model_config(data: dict[str, Any]) -> VisionModelConfig:
        queue_interval_seconds = _normalize_queue_interval(
            _coerce_float(
                _get_value(
                    data,
                    ("models", "vision", "queue_interval_seconds"),
                    "VISION_MODEL_QUEUE_INTERVAL",
                ),
                1.0,
            )
        )
        thinking_include_budget, thinking_tool_call_compat = (
            _resolve_thinking_compat_flags(
                data=data,
                model_name="vision",
                include_budget_env_key="VISION_MODEL_THINKING_INCLUDE_BUDGET",
                tool_call_compat_env_key="VISION_MODEL_THINKING_TOOL_CALL_COMPAT",
                legacy_env_key="VISION_MODEL_DEEPSEEK_NEW_COT_SUPPORT",
            )
        )
        api_mode = _resolve_api_mode(data, "vision", "VISION_MODEL_API_MODE")
        responses_tool_choice_compat = _resolve_responses_tool_choice_compat(
            data, "vision", "VISION_MODEL_RESPONSES_TOOL_CHOICE_COMPAT"
        )
        responses_force_stateless_replay = _resolve_responses_force_stateless_replay(
            data, "vision", "VISION_MODEL_RESPONSES_FORCE_STATELESS_REPLAY"
        )
        reasoning_enabled = _coerce_bool(
            _get_value(
                data,
                ("models", "vision", "reasoning_enabled"),
                "VISION_MODEL_REASONING_ENABLED",
            ),
            False,
        )
        reasoning_effort = _resolve_reasoning_effort(
            _get_value(
                data,
                ("models", "vision", "reasoning_effort"),
                "VISION_MODEL_REASONING_EFFORT",
            ),
            "medium",
        )
        return VisionModelConfig(
            api_url=_coerce_str(
                _get_value(
                    data, ("models", "vision", "api_url"), "VISION_MODEL_API_URL"
                ),
                "",
            ),
            api_key=_coerce_str(
                _get_value(
                    data, ("models", "vision", "api_key"), "VISION_MODEL_API_KEY"
                ),
                "",
            ),
            model_name=_coerce_str(
                _get_value(
                    data, ("models", "vision", "model_name"), "VISION_MODEL_NAME"
                ),
                "",
            ),
            queue_interval_seconds=queue_interval_seconds,
            api_mode=api_mode,
            thinking_enabled=_coerce_bool(
                _get_value(
                    data,
                    ("models", "vision", "thinking_enabled"),
                    "VISION_MODEL_THINKING_ENABLED",
                ),
                False,
            ),
            thinking_budget_tokens=_coerce_int(
                _get_value(
                    data,
                    ("models", "vision", "thinking_budget_tokens"),
                    "VISION_MODEL_THINKING_BUDGET_TOKENS",
                ),
                20000,
            ),
            thinking_include_budget=thinking_include_budget,
            reasoning_effort_style=_resolve_reasoning_effort_style(
                _get_value(
                    data,
                    ("models", "vision", "reasoning_effort_style"),
                    "VISION_MODEL_REASONING_EFFORT_STYLE",
                ),
            ),
            thinking_tool_call_compat=thinking_tool_call_compat,
            responses_tool_choice_compat=responses_tool_choice_compat,
            responses_force_stateless_replay=responses_force_stateless_replay,
            reasoning_enabled=reasoning_enabled,
            reasoning_effort=reasoning_effort,
            request_params=_get_model_request_params(data, "vision"),
        )

    @staticmethod
    def _parse_security_model_config(
        data: dict[str, Any], chat_model: ChatModelConfig
    ) -> SecurityModelConfig:
        api_url = _coerce_str(
            _get_value(
                data, ("models", "security", "api_url"), "SECURITY_MODEL_API_URL"
            ),
            "",
        )
        api_key = _coerce_str(
            _get_value(
                data, ("models", "security", "api_key"), "SECURITY_MODEL_API_KEY"
            ),
            "",
        )
        model_name = _coerce_str(
            _get_value(
                data, ("models", "security", "model_name"), "SECURITY_MODEL_NAME"
            ),
            "",
        )
        queue_interval_seconds = _coerce_float(
            _get_value(
                data,
                ("models", "security", "queue_interval_seconds"),
                "SECURITY_MODEL_QUEUE_INTERVAL",
            ),
            1.0,
        )
        queue_interval_seconds = _normalize_queue_interval(queue_interval_seconds)

        thinking_include_budget, thinking_tool_call_compat = (
            _resolve_thinking_compat_flags(
                data=data,
                model_name="security",
                include_budget_env_key="SECURITY_MODEL_THINKING_INCLUDE_BUDGET",
                tool_call_compat_env_key="SECURITY_MODEL_THINKING_TOOL_CALL_COMPAT",
                legacy_env_key="SECURITY_MODEL_DEEPSEEK_NEW_COT_SUPPORT",
            )
        )
        api_mode = _resolve_api_mode(data, "security", "SECURITY_MODEL_API_MODE")
        responses_tool_choice_compat = _resolve_responses_tool_choice_compat(
            data, "security", "SECURITY_MODEL_RESPONSES_TOOL_CHOICE_COMPAT"
        )
        responses_force_stateless_replay = _resolve_responses_force_stateless_replay(
            data, "security", "SECURITY_MODEL_RESPONSES_FORCE_STATELESS_REPLAY"
        )
        reasoning_enabled = _coerce_bool(
            _get_value(
                data,
                ("models", "security", "reasoning_enabled"),
                "SECURITY_MODEL_REASONING_ENABLED",
            ),
            False,
        )
        reasoning_effort = _resolve_reasoning_effort(
            _get_value(
                data,
                ("models", "security", "reasoning_effort"),
                "SECURITY_MODEL_REASONING_EFFORT",
            ),
            "medium",
        )

        if api_url and api_key and model_name:
            return SecurityModelConfig(
                api_url=api_url,
                api_key=api_key,
                model_name=model_name,
                max_tokens=_coerce_int(
                    _get_value(
                        data,
                        ("models", "security", "max_tokens"),
                        "SECURITY_MODEL_MAX_TOKENS",
                    ),
                    100,
                ),
                queue_interval_seconds=queue_interval_seconds,
                api_mode=api_mode,
                thinking_enabled=_coerce_bool(
                    _get_value(
                        data,
                        ("models", "security", "thinking_enabled"),
                        "SECURITY_MODEL_THINKING_ENABLED",
                    ),
                    False,
                ),
                thinking_budget_tokens=_coerce_int(
                    _get_value(
                        data,
                        ("models", "security", "thinking_budget_tokens"),
                        "SECURITY_MODEL_THINKING_BUDGET_TOKENS",
                    ),
                    0,
                ),
                thinking_include_budget=thinking_include_budget,
                reasoning_effort_style=_resolve_reasoning_effort_style(
                    _get_value(
                        data,
                        ("models", "security", "reasoning_effort_style"),
                        "SECURITY_MODEL_REASONING_EFFORT_STYLE",
                    ),
                ),
                thinking_tool_call_compat=thinking_tool_call_compat,
                responses_tool_choice_compat=responses_tool_choice_compat,
                responses_force_stateless_replay=responses_force_stateless_replay,
                reasoning_enabled=reasoning_enabled,
                reasoning_effort=reasoning_effort,
                request_params=_get_model_request_params(data, "security"),
            )

        logger.warning("未配置安全模型，将使用对话模型作为后备")
        return SecurityModelConfig(
            api_url=chat_model.api_url,
            api_key=chat_model.api_key,
            model_name=chat_model.model_name,
            max_tokens=chat_model.max_tokens,
            queue_interval_seconds=chat_model.queue_interval_seconds,
            api_mode=chat_model.api_mode,
            thinking_enabled=False,
            thinking_budget_tokens=0,
            thinking_include_budget=True,
            reasoning_effort_style="openai",
            thinking_tool_call_compat=chat_model.thinking_tool_call_compat,
            responses_tool_choice_compat=chat_model.responses_tool_choice_compat,
            responses_force_stateless_replay=chat_model.responses_force_stateless_replay,
            reasoning_enabled=chat_model.reasoning_enabled,
            reasoning_effort=chat_model.reasoning_effort,
            request_params=merge_request_params(chat_model.request_params),
        )

    @staticmethod
    def _parse_naga_model_config(
        data: dict[str, Any], security_model: SecurityModelConfig
    ) -> SecurityModelConfig:
        api_url = _coerce_str(
            _get_value(data, ("models", "naga", "api_url"), "NAGA_MODEL_API_URL"),
            "",
        )
        api_key = _coerce_str(
            _get_value(data, ("models", "naga", "api_key"), "NAGA_MODEL_API_KEY"),
            "",
        )
        model_name = _coerce_str(
            _get_value(data, ("models", "naga", "model_name"), "NAGA_MODEL_NAME"),
            "",
        )
        queue_interval_seconds = _coerce_float(
            _get_value(
                data,
                ("models", "naga", "queue_interval_seconds"),
                "NAGA_MODEL_QUEUE_INTERVAL",
            ),
            security_model.queue_interval_seconds,
        )
        queue_interval_seconds = _normalize_queue_interval(queue_interval_seconds)

        thinking_include_budget, thinking_tool_call_compat = (
            _resolve_thinking_compat_flags(
                data=data,
                model_name="naga",
                include_budget_env_key="NAGA_MODEL_THINKING_INCLUDE_BUDGET",
                tool_call_compat_env_key="NAGA_MODEL_THINKING_TOOL_CALL_COMPAT",
                legacy_env_key="NAGA_MODEL_DEEPSEEK_NEW_COT_SUPPORT",
            )
        )
        api_mode = _resolve_api_mode(data, "naga", "NAGA_MODEL_API_MODE")
        responses_tool_choice_compat = _resolve_responses_tool_choice_compat(
            data, "naga", "NAGA_MODEL_RESPONSES_TOOL_CHOICE_COMPAT"
        )
        responses_force_stateless_replay = _resolve_responses_force_stateless_replay(
            data, "naga", "NAGA_MODEL_RESPONSES_FORCE_STATELESS_REPLAY"
        )
        reasoning_enabled = _coerce_bool(
            _get_value(
                data,
                ("models", "naga", "reasoning_enabled"),
                "NAGA_MODEL_REASONING_ENABLED",
            ),
            getattr(security_model, "reasoning_enabled", False),
        )
        reasoning_effort = _resolve_reasoning_effort(
            _get_value(
                data,
                ("models", "naga", "reasoning_effort"),
                "NAGA_MODEL_REASONING_EFFORT",
            ),
            getattr(security_model, "reasoning_effort", "medium"),
        )

        if api_url and api_key and model_name:
            return SecurityModelConfig(
                api_url=api_url,
                api_key=api_key,
                model_name=model_name,
                max_tokens=_coerce_int(
                    _get_value(
                        data,
                        ("models", "naga", "max_tokens"),
                        "NAGA_MODEL_MAX_TOKENS",
                    ),
                    160,
                ),
                queue_interval_seconds=queue_interval_seconds,
                api_mode=api_mode,
                thinking_enabled=_coerce_bool(
                    _get_value(
                        data,
                        ("models", "naga", "thinking_enabled"),
                        "NAGA_MODEL_THINKING_ENABLED",
                    ),
                    False,
                ),
                thinking_budget_tokens=_coerce_int(
                    _get_value(
                        data,
                        ("models", "naga", "thinking_budget_tokens"),
                        "NAGA_MODEL_THINKING_BUDGET_TOKENS",
                    ),
                    0,
                ),
                thinking_include_budget=thinking_include_budget,
                reasoning_effort_style=_resolve_reasoning_effort_style(
                    _get_value(
                        data,
                        ("models", "naga", "reasoning_effort_style"),
                        "NAGA_MODEL_REASONING_EFFORT_STYLE",
                    ),
                ),
                thinking_tool_call_compat=thinking_tool_call_compat,
                responses_tool_choice_compat=responses_tool_choice_compat,
                responses_force_stateless_replay=responses_force_stateless_replay,
                reasoning_enabled=reasoning_enabled,
                reasoning_effort=reasoning_effort,
                request_params=_get_model_request_params(data, "naga"),
            )

        logger.info(
            "未配置 Naga 审核模型，将使用已解析的安全模型配置作为后备（安全模型本身可能已回退）"
        )
        return SecurityModelConfig(
            api_url=security_model.api_url,
            api_key=security_model.api_key,
            model_name=security_model.model_name,
            max_tokens=security_model.max_tokens,
            queue_interval_seconds=security_model.queue_interval_seconds,
            api_mode=security_model.api_mode,
            thinking_enabled=security_model.thinking_enabled,
            thinking_budget_tokens=security_model.thinking_budget_tokens,
            thinking_include_budget=security_model.thinking_include_budget,
            reasoning_effort_style=security_model.reasoning_effort_style,
            thinking_tool_call_compat=security_model.thinking_tool_call_compat,
            responses_tool_choice_compat=security_model.responses_tool_choice_compat,
            responses_force_stateless_replay=security_model.responses_force_stateless_replay,
            reasoning_enabled=security_model.reasoning_enabled,
            reasoning_effort=security_model.reasoning_effort,
            request_params=merge_request_params(security_model.request_params),
        )

    @staticmethod
    def _parse_agent_model_config(data: dict[str, Any]) -> AgentModelConfig:
        queue_interval_seconds = _normalize_queue_interval(
            _coerce_float(
                _get_value(
                    data,
                    ("models", "agent", "queue_interval_seconds"),
                    "AGENT_MODEL_QUEUE_INTERVAL",
                ),
                1.0,
            )
        )
        thinking_include_budget, thinking_tool_call_compat = (
            _resolve_thinking_compat_flags(
                data=data,
                model_name="agent",
                include_budget_env_key="AGENT_MODEL_THINKING_INCLUDE_BUDGET",
                tool_call_compat_env_key="AGENT_MODEL_THINKING_TOOL_CALL_COMPAT",
                legacy_env_key="AGENT_MODEL_DEEPSEEK_NEW_COT_SUPPORT",
            )
        )
        api_mode = _resolve_api_mode(data, "agent", "AGENT_MODEL_API_MODE")
        responses_tool_choice_compat = _resolve_responses_tool_choice_compat(
            data, "agent", "AGENT_MODEL_RESPONSES_TOOL_CHOICE_COMPAT"
        )
        responses_force_stateless_replay = _resolve_responses_force_stateless_replay(
            data, "agent", "AGENT_MODEL_RESPONSES_FORCE_STATELESS_REPLAY"
        )
        reasoning_enabled = _coerce_bool(
            _get_value(
                data,
                ("models", "agent", "reasoning_enabled"),
                "AGENT_MODEL_REASONING_ENABLED",
            ),
            False,
        )
        reasoning_effort = _resolve_reasoning_effort(
            _get_value(
                data,
                ("models", "agent", "reasoning_effort"),
                "AGENT_MODEL_REASONING_EFFORT",
            ),
            "medium",
        )
        config = AgentModelConfig(
            api_url=_coerce_str(
                _get_value(data, ("models", "agent", "api_url"), "AGENT_MODEL_API_URL"),
                "",
            ),
            api_key=_coerce_str(
                _get_value(data, ("models", "agent", "api_key"), "AGENT_MODEL_API_KEY"),
                "",
            ),
            model_name=_coerce_str(
                _get_value(data, ("models", "agent", "model_name"), "AGENT_MODEL_NAME"),
                "",
            ),
            max_tokens=_coerce_int(
                _get_value(
                    data, ("models", "agent", "max_tokens"), "AGENT_MODEL_MAX_TOKENS"
                ),
                4096,
            ),
            queue_interval_seconds=queue_interval_seconds,
            api_mode=api_mode,
            thinking_enabled=_coerce_bool(
                _get_value(
                    data,
                    ("models", "agent", "thinking_enabled"),
                    "AGENT_MODEL_THINKING_ENABLED",
                ),
                False,
            ),
            thinking_budget_tokens=_coerce_int(
                _get_value(
                    data,
                    ("models", "agent", "thinking_budget_tokens"),
                    "AGENT_MODEL_THINKING_BUDGET_TOKENS",
                ),
                0,
            ),
            thinking_include_budget=thinking_include_budget,
            reasoning_effort_style=_resolve_reasoning_effort_style(
                _get_value(
                    data,
                    ("models", "agent", "reasoning_effort_style"),
                    "AGENT_MODEL_REASONING_EFFORT_STYLE",
                ),
            ),
            thinking_tool_call_compat=thinking_tool_call_compat,
            responses_tool_choice_compat=responses_tool_choice_compat,
            responses_force_stateless_replay=responses_force_stateless_replay,
            reasoning_enabled=reasoning_enabled,
            reasoning_effort=reasoning_effort,
            request_params=_get_model_request_params(data, "agent"),
        )
        config.pool = Config._parse_model_pool(data, "agent", config)
        return config

    @staticmethod
    def _parse_grok_model_config(data: dict[str, Any]) -> GrokModelConfig:
        queue_interval_seconds = _normalize_queue_interval(
            _coerce_float(
                _get_value(
                    data,
                    ("models", "grok", "queue_interval_seconds"),
                    "GROK_MODEL_QUEUE_INTERVAL",
                ),
                1.0,
            )
        )
        return GrokModelConfig(
            api_url=_coerce_str(
                _get_value(data, ("models", "grok", "api_url"), "GROK_MODEL_API_URL"),
                "",
            ),
            api_key=_coerce_str(
                _get_value(data, ("models", "grok", "api_key"), "GROK_MODEL_API_KEY"),
                "",
            ),
            model_name=_coerce_str(
                _get_value(data, ("models", "grok", "model_name"), "GROK_MODEL_NAME"),
                "",
            ),
            max_tokens=_coerce_int(
                _get_value(
                    data, ("models", "grok", "max_tokens"), "GROK_MODEL_MAX_TOKENS"
                ),
                8192,
            ),
            queue_interval_seconds=queue_interval_seconds,
            thinking_enabled=_coerce_bool(
                _get_value(
                    data,
                    ("models", "grok", "thinking_enabled"),
                    "GROK_MODEL_THINKING_ENABLED",
                ),
                False,
            ),
            thinking_budget_tokens=_coerce_int(
                _get_value(
                    data,
                    ("models", "grok", "thinking_budget_tokens"),
                    "GROK_MODEL_THINKING_BUDGET_TOKENS",
                ),
                20000,
            ),
            thinking_include_budget=_coerce_bool(
                _get_value(
                    data,
                    ("models", "grok", "thinking_include_budget"),
                    "GROK_MODEL_THINKING_INCLUDE_BUDGET",
                ),
                True,
            ),
            reasoning_effort_style=_resolve_reasoning_effort_style(
                _get_value(
                    data,
                    ("models", "grok", "reasoning_effort_style"),
                    "GROK_MODEL_REASONING_EFFORT_STYLE",
                ),
            ),
            reasoning_enabled=_coerce_bool(
                _get_value(
                    data,
                    ("models", "grok", "reasoning_enabled"),
                    "GROK_MODEL_REASONING_ENABLED",
                ),
                False,
            ),
            reasoning_effort=_resolve_reasoning_effort(
                _get_value(
                    data,
                    ("models", "grok", "reasoning_effort"),
                    "GROK_MODEL_REASONING_EFFORT",
                ),
                "medium",
            ),
            request_params=_get_model_request_params(data, "grok"),
        )

    @staticmethod
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
            request_params=_get_model_request_params(data, "image_gen"),
        )

    @staticmethod
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
            request_params=_get_model_request_params(data, "image_edit"),
        )

    @staticmethod
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
        )

    @staticmethod
    def _merge_admins(
        superadmin_qq: int, admin_qqs: list[int]
    ) -> tuple[int, list[int]]:
        local_admins = load_local_admins()
        all_admins = list(set(admin_qqs + local_admins))
        if superadmin_qq and superadmin_qq not in all_admins:
            all_admins.append(superadmin_qq)
        return superadmin_qq, all_admins

    @staticmethod
    def _verify_required_fields(
        bot_qq: int,
        superadmin_qq: int,
        onebot_ws_url: str,
        chat_model: ChatModelConfig,
        vision_model: VisionModelConfig,
        agent_model: AgentModelConfig,
        knowledge_enabled: bool,
        embedding_model: EmbeddingModelConfig,
    ) -> None:
        missing: list[str] = []
        if bot_qq <= 0:
            missing.append("core.bot_qq")
        if superadmin_qq <= 0:
            missing.append("core.superadmin_qq")
        if not onebot_ws_url:
            missing.append("onebot.ws_url")
        if not chat_model.api_url:
            missing.append("models.chat.api_url")
        if not chat_model.api_key:
            missing.append("models.chat.api_key")
        if not chat_model.model_name:
            missing.append("models.chat.model_name")
        if not vision_model.api_url:
            missing.append("models.vision.api_url")
        if not vision_model.api_key:
            missing.append("models.vision.api_key")
        if not vision_model.model_name:
            missing.append("models.vision.model_name")
        if not agent_model.api_url:
            missing.append("models.agent.api_url")
        if not agent_model.api_key:
            missing.append("models.agent.api_key")
        if not agent_model.model_name:
            missing.append("models.agent.model_name")
        if knowledge_enabled:
            if not embedding_model.api_url:
                missing.append("models.embedding.api_url")
            if not embedding_model.model_name:
                missing.append("models.embedding.model_name")
        if missing:
            raise ValueError(f"缺少必需配置: {', '.join(missing)}")

    @staticmethod
    def _log_debug_info(
        chat_model: ChatModelConfig,
        vision_model: VisionModelConfig,
        security_model: SecurityModelConfig,
        naga_model: SecurityModelConfig,
        agent_model: AgentModelConfig,
        grok_model: GrokModelConfig,
    ) -> None:
        configs: list[
            tuple[
                str,
                ChatModelConfig
                | VisionModelConfig
                | SecurityModelConfig
                | AgentModelConfig
                | GrokModelConfig,
            ]
        ] = [
            ("chat", chat_model),
            ("vision", vision_model),
            ("security", security_model),
            ("naga", naga_model),
            ("agent", agent_model),
            ("grok", grok_model),
        ]
        for name, cfg in configs:
            logger.debug(
                "[配置] %s_model=%s api_url=%s api_key_set=%s api_mode=%s thinking=%s reasoning=%s/%s cot_compat=%s responses_tool_choice_compat=%s responses_force_stateless_replay=%s",
                name,
                cfg.model_name,
                cfg.api_url,
                bool(cfg.api_key),
                getattr(cfg, "api_mode", "chat_completions"),
                cfg.thinking_enabled,
                getattr(cfg, "reasoning_enabled", False),
                getattr(cfg, "reasoning_effort", "medium"),
                getattr(cfg, "thinking_tool_call_compat", False),
                getattr(cfg, "responses_tool_choice_compat", False),
                getattr(cfg, "responses_force_stateless_replay", False),
            )

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

    @staticmethod
    def _parse_historian_model_config(
        data: dict[str, Any], fallback: AgentModelConfig
    ) -> AgentModelConfig:
        h = data.get("models", {}).get("historian", {})
        if not isinstance(h, dict) or not h:
            return fallback
        queue_interval_seconds = _coerce_float(
            h.get("queue_interval_seconds"), fallback.queue_interval_seconds
        )
        queue_interval_seconds = _normalize_queue_interval(
            queue_interval_seconds, fallback.queue_interval_seconds
        )
        thinking_include_budget, thinking_tool_call_compat = (
            _resolve_thinking_compat_flags(
                data={"models": {"historian": h}},
                model_name="historian",
                include_budget_env_key="HISTORIAN_MODEL_THINKING_INCLUDE_BUDGET",
                tool_call_compat_env_key="HISTORIAN_MODEL_THINKING_TOOL_CALL_COMPAT",
                legacy_env_key="HISTORIAN_MODEL_DEEPSEEK_NEW_COT_SUPPORT",
            )
        )
        api_mode = _resolve_api_mode(
            {"models": {"historian": h}},
            "historian",
            "HISTORIAN_MODEL_API_MODE",
            fallback.api_mode,
        )
        responses_tool_choice_compat = _resolve_responses_tool_choice_compat(
            {"models": {"historian": h}},
            "historian",
            "HISTORIAN_MODEL_RESPONSES_TOOL_CHOICE_COMPAT",
            fallback.responses_tool_choice_compat,
        )
        responses_force_stateless_replay = _resolve_responses_force_stateless_replay(
            {"models": {"historian": h}},
            "historian",
            "HISTORIAN_MODEL_RESPONSES_FORCE_STATELESS_REPLAY",
            fallback.responses_force_stateless_replay,
        )
        return AgentModelConfig(
            api_url=_coerce_str(h.get("api_url"), fallback.api_url),
            api_key=_coerce_str(h.get("api_key"), fallback.api_key),
            model_name=_coerce_str(h.get("model_name"), fallback.model_name),
            max_tokens=_coerce_int(h.get("max_tokens"), fallback.max_tokens),
            queue_interval_seconds=queue_interval_seconds,
            api_mode=api_mode,
            thinking_enabled=_coerce_bool(
                h.get("thinking_enabled"), fallback.thinking_enabled
            ),
            thinking_budget_tokens=_coerce_int(
                h.get("thinking_budget_tokens"), fallback.thinking_budget_tokens
            ),
            thinking_include_budget=thinking_include_budget,
            reasoning_effort_style=_resolve_reasoning_effort_style(
                _get_value(
                    {"models": {"historian": h}},
                    ("models", "historian", "reasoning_effort_style"),
                    "HISTORIAN_MODEL_REASONING_EFFORT_STYLE",
                ),
                fallback.reasoning_effort_style,
            ),
            thinking_tool_call_compat=thinking_tool_call_compat,
            responses_tool_choice_compat=responses_tool_choice_compat,
            responses_force_stateless_replay=responses_force_stateless_replay,
            reasoning_enabled=_coerce_bool(
                _get_value(
                    {"models": {"historian": h}},
                    ("models", "historian", "reasoning_enabled"),
                    "HISTORIAN_MODEL_REASONING_ENABLED",
                ),
                fallback.reasoning_enabled,
            ),
            reasoning_effort=_resolve_reasoning_effort(
                _get_value(
                    {"models": {"historian": h}},
                    ("models", "historian", "reasoning_effort"),
                    "HISTORIAN_MODEL_REASONING_EFFORT",
                ),
                fallback.reasoning_effort,
            ),
            request_params=merge_request_params(
                fallback.request_params,
                h.get("request_params"),
            ),
        )

    @staticmethod
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
            auto_top_k=_coerce_int(
                q.get("auto_top_k") if isinstance(q, dict) else None, 3
            ),
            auto_scope_candidate_multiplier=_coerce_int(
                q.get("auto_scope_candidate_multiplier")
                if isinstance(q, dict)
                else None,
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
                q.get("time_decay_half_life_days_auto")
                if isinstance(q, dict)
                else None,
                14.0,
            ),
            time_decay_half_life_days_tool=_coerce_float(
                q.get("time_decay_half_life_days_tool")
                if isinstance(q, dict)
                else None,
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
                hist.get("recent_messages_inject_k")
                if isinstance(hist, dict)
                else None,
                12,
            ),
            historian_recent_message_line_max_len=_coerce_int(
                hist.get("recent_message_line_max_len")
                if isinstance(hist, dict)
                else None,
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
                hist.get("stale_job_timeout_seconds")
                if isinstance(hist, dict)
                else None,
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

    @staticmethod
    def _parse_memes_config(data: dict[str, Any]) -> MemeConfig:
        section_raw = data.get("memes", {})
        section = section_raw if isinstance(section_raw, dict) else {}
        return MemeConfig(
            enabled=_coerce_bool(section.get("enabled"), True),
            query_default_mode=_coerce_str(section.get("query_default_mode"), "hybrid"),
            max_source_image_bytes=max(
                1,
                _coerce_int(section.get("max_source_image_bytes"), 1024 * 1024),
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
        )

    @staticmethod
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

    @staticmethod
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

    @staticmethod
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
