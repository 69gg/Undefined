"""Config dataclass and instance methods."""

from __future__ import annotations


from dataclasses import dataclass, field as dataclass_field, fields
from pathlib import Path
from typing import Any, Optional

from .admin import load_local_admins, save_local_admins
from .domain_parsers import _update_dataclass
from .models import (
    AgentModelConfig,
    APIConfig,
    ChatModelConfig,
    CognitiveConfig,
    EmbeddingModelConfig,
    GrokModelConfig,
    ImageGenConfig,
    ImageGenModelConfig,
    MemeConfig,
    MessageBatcherConfig,
    NagaConfig,
    PromptSystemInfoConfig,
    RenderCacheConfig,
    RerankModelConfig,
    SecurityModelConfig,
    VisionModelConfig,
)
from .toml_io import _load_env, load_toml_data


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
    missing_tool_call_retries: int
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
    attachment_use_proxy: bool
    attachment_remote_download_max_size_mb: int
    attachment_cache_max_total_size_mb: int
    attachment_cache_max_records: int
    attachment_cache_max_age_days: int
    attachment_url_reference_max_records: int
    attachment_url_max_length: int
    skills_hot_reload: bool
    skills_hot_reload_interval: float
    skills_hot_reload_debounce: float
    agent_intro_autogen_enabled: bool
    agent_intro_autogen_queue_interval: float
    agent_intro_autogen_max_tokens: int
    agent_intro_hash_path: str
    search_priority: list[str]
    searxng_url: str
    grok_search_enabled: bool
    firecrawl_search_enabled: bool
    firecrawl_api_key: str
    firecrawl_base_url: str
    search_use_proxy: bool
    http_proxy: str
    https_proxy: str
    network_request_timeout: float
    network_request_retries: int
    render_browser_max_concurrency: int
    render_use_proxy: bool
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
    webui_autostart_bot: bool
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
    messages_use_proxy: bool
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
    bilibili_use_proxy: bool
    bilibili_auto_extract_enabled: bool
    bilibili_cookie: str
    bilibili_prefer_quality: int
    bilibili_max_duration: int
    bilibili_max_file_size: int
    bilibili_oversize_strategy: str
    bilibili_danmaku_enabled: bool
    bilibili_danmaku_batch_size: int
    bilibili_danmaku_max_count: int
    bilibili_auto_extract_group_ids: list[int]
    bilibili_auto_extract_private_ids: list[int]
    # Douyin 视频提取
    douyin_use_proxy: bool
    douyin_auto_extract_enabled: bool
    douyin_max_duration: int
    douyin_max_file_size: int
    douyin_prefer_ratios: list[str]
    douyin_auto_extract_group_ids: list[int]
    douyin_auto_extract_private_ids: list[int]
    douyin_auto_extract_max_items: int
    # arXiv 论文提取
    arxiv_use_proxy: bool
    arxiv_auto_extract_enabled: bool
    arxiv_max_file_size: int
    arxiv_auto_extract_group_ids: list[int]
    arxiv_auto_extract_private_ids: list[int]
    arxiv_auto_extract_max_items: int
    arxiv_author_preview_limit: int
    arxiv_summary_preview_chars: int
    # GitHub 仓库自动提取
    github_use_proxy: bool
    github_auto_extract_enabled: bool
    github_request_timeout_seconds: float
    github_request_retries: int
    github_auto_extract_group_ids: list[int]
    github_auto_extract_private_ids: list[int]
    github_auto_extract_max_items: int
    # 认知记忆
    cognitive: CognitiveConfig
    # 表情包库
    memes: MemeConfig
    # 同 sender 短时多消息合并器
    message_batcher: MessageBatcherConfig
    # Prompt 系统信息注入
    prompt_system_info: PromptSystemInfoConfig
    # HTML 渲染结果缓存
    render_cache: RenderCacheConfig
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
    _douyin_group_ids_set: set[int] = dataclass_field(
        default_factory=set,
        init=False,
        repr=False,
    )
    _douyin_private_ids_set: set[int] = dataclass_field(
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
    _github_group_ids_set: set[int] = dataclass_field(
        default_factory=set,
        init=False,
        repr=False,
    )
    _github_private_ids_set: set[int] = dataclass_field(
        default_factory=set,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self._refresh_runtime_sets()

    def _refresh_runtime_sets(self) -> None:
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
        self._douyin_group_ids_set = {
            int(item) for item in self.douyin_auto_extract_group_ids
        }
        self._douyin_private_ids_set = {
            int(item) for item in self.douyin_auto_extract_private_ids
        }
        self._arxiv_group_ids_set = {
            int(item) for item in self.arxiv_auto_extract_group_ids
        }
        self._arxiv_private_ids_set = {
            int(item) for item in self.arxiv_auto_extract_private_ids
        }
        self._github_group_ids_set = {
            int(item) for item in self.github_auto_extract_group_ids
        }
        self._github_private_ids_set = {
            int(item) for item in self.github_auto_extract_private_ids
        }

    @classmethod
    def load(cls, config_path: Optional[Path] = None, strict: bool = True) -> "Config":
        """从 config.toml 和本地配置加载配置"""
        from .build_config import build_config

        _load_env()  # 先加载 .env，供 _get_value 环境变量回退
        data = load_toml_data(config_path, strict=strict)
        return build_config(data, strict=strict, config_path=config_path)

    @classmethod
    def from_mapping(cls, data: dict[str, Any], *, strict: bool = True) -> "Config":
        """从内存 mapping 构建配置（无 TOML 文件）。"""
        from .build_config import build_config

        return build_config(data, strict=strict, config_path=None)

    @classmethod
    def builder(cls) -> "ConfigBuilder":
        """返回可链式覆盖字段的配置构建器。"""
        return ConfigBuilder()

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

    def is_douyin_auto_extract_allowed_group(self, group_id: int) -> bool:
        """群聊是否允许 Douyin 自动提取。"""
        if self._douyin_group_ids_set:
            return int(group_id) in self._douyin_group_ids_set
        return self.is_group_allowed(group_id)

    def is_douyin_auto_extract_allowed_private(self, user_id: int) -> bool:
        """私聊是否允许 Douyin 自动提取。"""
        if self._douyin_private_ids_set:
            return int(user_id) in self._douyin_private_ids_set
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

    def is_github_auto_extract_allowed_group(self, group_id: int) -> bool:
        """群聊是否允许 GitHub 仓库自动提取。"""
        if self._github_group_ids_set:
            return int(group_id) in self._github_group_ids_set
        return self.is_group_allowed(group_id)

    def is_github_auto_extract_allowed_private(self, user_id: int) -> bool:
        """私聊是否允许 GitHub 仓库自动提取。"""
        if self._github_private_ids_set:
            return int(user_id) in self._github_private_ids_set
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
        return limit

    def security_check_enabled(self) -> bool:
        """是否启用安全模型检查。"""
        # 热更新运行时参数

        return bool(self.security_model_enabled)

    # 热更新运行时参数
    def update_from(self, new_config: "Config") -> dict[str, tuple[Any, Any]]:
        # 逐字段 diff；嵌套模型配置用 _update_dataclass 展开为 chat_model.api_url 等键
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
        if changes:
            self._refresh_runtime_sets()
        return changes

    def reload(self, strict: bool = False) -> dict[str, tuple[Any, Any]]:
        # 对外入队 API
        new_config = Config.load(strict=strict)
        return self.update_from(new_config)

    # 对外入队 API
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


class ConfigBuilder:
    """链式构建 Config；未设置的字段使用 build_config 默认值。"""

    def __init__(self) -> None:
        self._overrides: dict[str, Any] = {}

    def with_mapping(self, data: dict[str, Any]) -> "ConfigBuilder":
        self._overrides["_base_mapping"] = data
        return self

    def override(self, **kwargs: Any) -> "ConfigBuilder":
        self._overrides.update(kwargs)
        return self

    # 从中间态构建最终对象
    def build(self, *, strict: bool = True) -> Config:
        from .build_config import build_config

        base = self._overrides.pop("_base_mapping", {})
        if not isinstance(base, dict):
            base = {}
        data = dict(base)
        # TOML-style nested overrides for simple top-level keys only
        for key, value in self._overrides.items():
            data[key] = value
        return build_config(data, strict=strict, config_path=None)
