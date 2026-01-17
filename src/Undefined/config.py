"""配置加载模块"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# 本地配置文件路径
LOCAL_CONFIG_PATH = Path("config.local.json")


@dataclass
class ChatModelConfig:
    """对话模型配置"""

    api_url: str
    api_key: str
    model_name: str
    max_tokens: int
    thinking_enabled: bool = False  # 是否启用 thinking
    thinking_budget_tokens: int = 20000  # 思维预算 token 数量


@dataclass
class VisionModelConfig:
    """视觉模型配置"""

    api_url: str
    api_key: str
    model_name: str
    thinking_enabled: bool = False  # 是否启用 thinking
    thinking_budget_tokens: int = 20000  # 思维预算 token 数量


@dataclass
class SecurityModelConfig:
    """安全模型配置（用于防注入检测和注入后的回复生成）"""

    api_url: str
    api_key: str
    model_name: str
    max_tokens: int
    thinking_enabled: bool = False  # 是否启用 thinking
    thinking_budget_tokens: int = 0  # 思维预算 token 数量


@dataclass
class AgentModelConfig:
    """Agent 模型配置（用于执行 agents）"""

    api_url: str
    api_key: str
    model_name: str
    max_tokens: int = 4096
    thinking_enabled: bool = False  # 是否启用 thinking
    thinking_budget_tokens: int = 0  # 思维预算 token 数量


def load_local_admins() -> list[int]:
    """从本地配置文件加载动态管理员列表"""
    if not LOCAL_CONFIG_PATH.exists():
        return []

    try:
        with open(LOCAL_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        admin_qqs: list[int] = data.get("admin_qqs", [])
        return admin_qqs
    except Exception as e:
        logger.warning(f"读取本地配置失败: {e}")
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

        logger.info(f"已保存管理员列表到 {LOCAL_CONFIG_PATH}")
    except Exception as e:
        logger.error(f"保存本地配置失败: {e}")
        raise


@dataclass
class Config:
    """应用配置"""

    bot_qq: int
    superadmin_qq: int  # 超级管理员（唯一）
    admin_qqs: list[int]  # 管理员列表（来自 .env + 本地配置）
    forward_proxy_qq: int | None  # 音频转发代理QQ号（可选，用于群聊音频转发）
    onebot_ws_url: str
    onebot_token: str
    chat_model: ChatModelConfig
    vision_model: VisionModelConfig
    security_model: SecurityModelConfig  # 安全模型（防注入检测和回复生成）
    agent_model: AgentModelConfig  # Agent 模型（用于执行各种 Agent）
    log_file_path: str
    log_max_size: int
    log_backup_count: int

    @classmethod
    def load(cls) -> "Config":
        """从环境变量和本地配置加载配置"""
        load_dotenv()

        # 验证必需的环境变量
        required_vars = [
            "BOT_QQ",
            "SUPERADMIN_QQ",
            "ONEBOT_WS_URL",
            "CHAT_MODEL_API_URL",
            "CHAT_MODEL_API_KEY",
            "CHAT_MODEL_NAME",
            "CHAT_MODEL_MAX_TOKENS",
            "VISION_MODEL_API_URL",
            "VISION_MODEL_API_KEY",
            "VISION_MODEL_NAME",
            "AGENT_MODEL_API_URL",
            "AGENT_MODEL_API_KEY",
            "AGENT_MODEL_NAME",
        ]

        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            raise ValueError(f"缺少必需的环境变量: {', '.join(missing)}")

        chat_model = ChatModelConfig(
            api_url=os.getenv("CHAT_MODEL_API_URL", ""),
            api_key=os.getenv("CHAT_MODEL_API_KEY", ""),
            model_name=os.getenv("CHAT_MODEL_NAME", ""),
            max_tokens=int(os.getenv("CHAT_MODEL_MAX_TOKENS", "8000")),
            thinking_enabled=os.getenv("CHAT_MODEL_THINKING_ENABLED", "false").lower()
            == "true",
            thinking_budget_tokens=int(
                os.getenv("CHAT_MODEL_THINKING_BUDGET_TOKENS", "20000")
            ),
        )

        vision_model = VisionModelConfig(
            api_url=os.getenv("VISION_MODEL_API_URL", ""),
            api_key=os.getenv("VISION_MODEL_API_KEY", ""),
            model_name=os.getenv("VISION_MODEL_NAME", ""),
            thinking_enabled=os.getenv("VISION_MODEL_THINKING_ENABLED", "false").lower()
            == "true",
            thinking_budget_tokens=int(
                os.getenv("VISION_MODEL_THINKING_BUDGET_TOKENS", "20000")
            ),
        )

        # 安全模型配置（防注入检测和回复生成）
        # 如果没有配置，则使用对话模型作为后备
        security_model_api_url = os.getenv("SECURITY_MODEL_API_URL", "")
        security_model_api_key = os.getenv("SECURITY_MODEL_API_KEY", "")
        security_model_name = os.getenv("SECURITY_MODEL_NAME", "")

        if security_model_api_url and security_model_api_key and security_model_name:
            # 使用独立的安全模型配置
            security_model = SecurityModelConfig(
                api_url=security_model_api_url,
                api_key=security_model_api_key,
                model_name=security_model_name,
                max_tokens=int(os.getenv("SECURITY_MODEL_MAX_TOKENS", "100")),
                thinking_enabled=os.getenv(
                    "SECURITY_MODEL_THINKING_ENABLED", "false"
                ).lower()
                == "true",
                thinking_budget_tokens=int(
                    os.getenv("SECURITY_MODEL_THINKING_BUDGET_TOKENS", "0")
                ),
            )
        else:
            # 如果没有配置，则使用对话模型作为后备
            logger.warning("未配置安全模型，将使用对话模型作为后备")
            security_model = SecurityModelConfig(
                api_url=chat_model.api_url,
                api_key=chat_model.api_key,
                model_name=chat_model.model_name,
                max_tokens=chat_model.max_tokens,
                thinking_enabled=False,
                thinking_budget_tokens=0,
            )

        # Agent 模型配置
        agent_model = AgentModelConfig(
            api_url=os.getenv("AGENT_MODEL_API_URL", ""),
            api_key=os.getenv("AGENT_MODEL_API_KEY", ""),
            model_name=os.getenv("AGENT_MODEL_NAME", ""),
            max_tokens=int(os.getenv("AGENT_MODEL_MAX_TOKENS", "4096")),
            thinking_enabled=os.getenv("AGENT_MODEL_THINKING_ENABLED", "false").lower()
            == "true",
            thinking_budget_tokens=int(
                os.getenv("AGENT_MODEL_THINKING_BUDGET_TOKENS", "0")
            ),
        )

        # 解析超级管理员
        superadmin_qq = int(os.getenv("SUPERADMIN_QQ", "0"))

        # 解析 .env 中的管理员列表
        admin_qq_str = os.getenv("ADMIN_QQ", "")
        env_admins: list[int] = []
        if admin_qq_str:
            try:
                env_admins = [
                    int(qq.strip()) for qq in admin_qq_str.split(",") if qq.strip()
                ]
            except ValueError:
                raise ValueError("ADMIN_QQ 格式错误，应为逗号分隔的数字")

        # 合并本地配置的管理员
        local_admins = load_local_admins()
        all_admins = list(set(env_admins + local_admins))

        # 确保超级管理员也在管理员列表中
        if superadmin_qq and superadmin_qq not in all_admins:
            all_admins.append(superadmin_qq)

        # 日志配置
        log_file_path = os.getenv("LOG_FILE_PATH", "logs/bot.log")
        log_max_size = (
            int(os.getenv("LOG_MAX_SIZE_MB", "10")) * 1024 * 1024
        )  # 转换为字节
        log_backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))

        # 音频转发代理QQ号（可选）
        forward_proxy_qq_str = os.getenv("FORWARD_PROXY_QQ")
        forward_proxy_qq = None
        if forward_proxy_qq_str and forward_proxy_qq_str.strip():
            try:
                forward_proxy_qq = int(forward_proxy_qq_str.strip())
            except ValueError:
                logger.warning(f"FORWARD_PROXY_QQ 格式错误: {forward_proxy_qq_str}")

        return cls(
            bot_qq=int(os.getenv("BOT_QQ", "0")),
            superadmin_qq=superadmin_qq,
            admin_qqs=all_admins,
            forward_proxy_qq=forward_proxy_qq,
            onebot_ws_url=os.getenv("ONEBOT_WS_URL", ""),
            onebot_token=os.getenv("ONEBOT_TOKEN", ""),
            chat_model=chat_model,
            vision_model=vision_model,
            security_model=security_model,
            agent_model=agent_model,
            log_file_path=log_file_path,
            log_max_size=log_max_size,
            log_backup_count=log_backup_count,
        )

    def reload(self) -> None:
        """热重载配置（重新加载管理员列表等动态配置）"""
        # 重新加载本地管理员
        local_admins = load_local_admins()

        # 重新读取 .env 中的管理员
        load_dotenv(override=True)
        admin_qq_str = os.getenv("ADMIN_QQ", "")
        env_admins: list[int] = []
        if admin_qq_str:
            try:
                env_admins = [
                    int(qq.strip()) for qq in admin_qq_str.split(",") if qq.strip()
                ]
            except ValueError:
                logger.warning("ADMIN_QQ 格式错误")

        # 合并管理员列表
        all_admins = list(set(env_admins + local_admins))
        if self.superadmin_qq and self.superadmin_qq not in all_admins:
            all_admins.append(self.superadmin_qq)

        self.admin_qqs = all_admins
        logger.info(f"配置已重载，管理员: {self.admin_qqs}")

    def add_admin(self, qq: int) -> bool:
        """添加管理员（保存到本地配置）

        参数:
            qq: 要添加的 QQ 号

        返回:
            是否添加成功（已存在返回 False）
        """
        if qq in self.admin_qqs:
            return False

        self.admin_qqs.append(qq)

        # 获取当前本地管理员并添加新的
        local_admins = load_local_admins()
        if qq not in local_admins:
            local_admins.append(qq)
            save_local_admins(local_admins)

        return True

    def remove_admin(self, qq: int) -> bool:
        """移除管理员（从本地配置中移除）

        参数:
            qq: 要移除的 QQ 号

        返回:
            是否移除成功
        """
        # 不能移除超级管理员
        if qq == self.superadmin_qq:
            return False

        if qq not in self.admin_qqs:
            return False

        self.admin_qqs.remove(qq)

        # 从本地配置中移除
        local_admins = load_local_admins()
        if qq in local_admins:
            local_admins.remove(qq)
            save_local_admins(local_admins)

        return True

    def is_superadmin(self, qq: int) -> bool:
        """检查是否为超级管理员

        参数:
            qq: QQ 号

        返回:
            是否为超级管理员
        """
        return qq == self.superadmin_qq

    def is_admin(self, qq: int) -> bool:
        """检查是否为管理员

        参数:
            qq: QQ 号

        返回:
            是否为管理员
        """
        return qq in self.admin_qqs


# 全局配置实例
_config: Optional[Config] = None


def get_config() -> Config:
    """获取配置实例（单例模式）"""
    global _config
    if _config is None:
        _config = Config.load()
    return _config
