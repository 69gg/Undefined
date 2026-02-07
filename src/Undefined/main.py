"""程序入口"""

import asyncio
import logging
import time
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler
from rich.console import Console

from Undefined.ai import AIClient
from Undefined.config import get_config, get_config_manager
from Undefined.config.hot_reload import HotReloadContext, apply_config_updates
from Undefined.config.loader import Config
from Undefined.context import RequestContextFilter
from Undefined.faq import FAQStorage
from Undefined.handlers import MessageHandler
from Undefined.memory import MemoryStorage
from Undefined.scheduled_task_storage import ScheduledTaskStorage
from Undefined.end_summary_storage import EndSummaryStorage
from Undefined.onebot import OneBotClient
from Undefined.token_usage_storage import TokenUsageStorage
from Undefined.utils.paths import (
    CACHE_DIR,
    DATA_DIR,
    DOWNLOAD_CACHE_DIR,
    IMAGE_CACHE_DIR,
    RENDER_CACHE_DIR,
    ensure_dir,
)


def ensure_runtime_dirs() -> None:
    """确保运行时目录存在"""
    runtime_dirs = [
        DATA_DIR,
        Path("data/history"),
        Path("data/faq"),
        Path("data/scheduler_context"),
        CACHE_DIR,
        RENDER_CACHE_DIR,
        IMAGE_CACHE_DIR,
        DOWNLOAD_CACHE_DIR,
    ]
    for path in runtime_dirs:
        ensure_dir(path)


def setup_logging() -> None:
    """设置日志（控制台 + 文件轮转）"""
    config = Config.load(strict=False)
    level, log_level = _get_log_level(config)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 1. 控制台处理器
    _init_console_handler(root_logger, level)

    # 2. 文件处理器
    _init_file_handler(root_logger, config)

    logging.info(f"[启动] 日志系统初始化完成。级别: {log_level}")


def _get_log_level(config: Config) -> tuple[int, str]:
    """从环境变量获取日志级别"""
    log_level = config.log_level.upper()
    level = getattr(logging, log_level, logging.INFO)
    return level, log_level


def _init_console_handler(root_logger: logging.Logger, level: int) -> None:
    """初始化控制台 Rich 日志处理器"""
    console = Console(force_terminal=True)
    handler = RichHandler(
        level=level,
        console=console,
        show_time=True,
        show_path=True,
        markup=True,
        rich_tracebacks=True,
    )
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    root_logger.addHandler(handler)


def _init_file_handler(root_logger: logging.Logger, config: Config) -> None:
    """初始化文件轮转日志处理器"""
    log_file_path = config.log_file_path
    log_max_size = config.log_max_size
    log_backup_count = config.log_backup_count

    log_dir = Path(log_file_path).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    file_log_format = (
        "%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s"
    )
    handler = RotatingFileHandler(
        log_file_path,
        maxBytes=log_max_size,
        backupCount=log_backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(file_log_format))
    handler.addFilter(RequestContextFilter())
    root_logger.addHandler(handler)


async def main() -> None:
    """主函数"""
    setup_logging()
    ensure_runtime_dirs()
    logger = logging.getLogger(__name__)
    logger.info("[启动] 正在初始化 Undefined 机器人...")

    start_time = time.perf_counter()
    try:
        did_compact = await TokenUsageStorage().compact_if_needed()
        elapsed = time.perf_counter() - start_time
        logger.info(
            "[Token统计] 启动归档检查完成: compacted=%s elapsed=%.3fs",
            did_compact,
            elapsed,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - start_time
        logger.warning(
            "[Token统计] 启动时归档检查失败: %s elapsed=%.3fs",
            exc,
            elapsed,
        )

    try:
        config = get_config()
        logger.info(f"[配置] 机器人 QQ: {config.bot_qq}")
        logger.info(f"[配置] 超级管理员: {config.superadmin_qq}")
        logger.info(f"[配置] 管理员 QQ 列表: {config.admin_qqs}")
    except ValueError as e:
        logger.error(f"[配置错误] 加载配置失败: {e}")
        sys.exit(1)

    # 初始化组件
    logger.info("[初始化] 正在加载核心组件...")
    try:
        onebot = OneBotClient(config.onebot_ws_url, config.onebot_token)
        memory_storage = MemoryStorage(max_memories=100)
        task_storage = ScheduledTaskStorage()
        end_summary_storage = EndSummaryStorage()
        ai = AIClient(
            config.chat_model,
            config.vision_model,
            config.agent_model,
            memory_storage,
            end_summary_storage,
            bot_qq=config.bot_qq,
            runtime_config=config,
        )
        faq_storage = FAQStorage()

        handler = MessageHandler(config, onebot, ai, faq_storage, task_storage)
        onebot.set_message_handler(handler.handle_message)
        logger.info("[初始化] 核心组件加载完成")
    except Exception as e:
        logger.exception(f"[初始化错误] 组件初始化期间发生异常: {e}")
        sys.exit(1)

    logger.info("[启动] 机器人已准备就绪，开始连接 OneBot 服务...")

    config_manager = get_config_manager()
    config_manager.load(strict=True)

    hot_reload_context = HotReloadContext(
        ai_client=ai,
        queue_manager=handler.queue_manager,
        config_manager=config_manager,
    )

    def _apply_config_updates(
        updated: Config, changes: dict[str, tuple[object, object]]
    ) -> None:
        apply_config_updates(updated, changes, hot_reload_context)

    config_manager.subscribe(_apply_config_updates)
    config_manager.start_hot_reload(
        interval=config.skills_hot_reload_interval,
        debounce=config.skills_hot_reload_debounce,
    )

    try:
        await onebot.run_with_reconnect()
    except KeyboardInterrupt:
        logger.info("[退出] 收到退出信号 (Ctrl+C)")
    except Exception as e:
        logger.exception(f"[异常] 运行期间发生未捕获的错误: {e}")
    finally:
        logger.info("[清理] 正在关闭机器人并释放资源...")
        await onebot.disconnect()
        await ai.close()
        await config_manager.stop_hot_reload()
        logger.info("[退出] 机器人已停止运行")


def run() -> None:
    """运行入口"""
    asyncio.run(main())


if __name__ == "__main__":
    run()
