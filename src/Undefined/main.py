"""程序入口"""

import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

from .ai import AIClient
from .config import get_config
from .faq import FAQStorage
from .handlers import MessageHandler
from .memory import MemoryStorage
from .scheduled_task_storage import ScheduledTaskStorage
from .end_summary_storage import EndSummaryStorage
from .onebot import OneBotClient


def setup_logging() -> None:
    """设置日志（控制台 + 文件轮转）"""
    load_dotenv()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level, logging.INFO)

    # 日志格式
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    formatter = logging.Formatter(log_format)

    # 根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 日志文件配置
    log_file_path = os.getenv("LOG_FILE_PATH", "logs/bot.log")
    log_max_size = (
        int(os.getenv("LOG_MAX_SIZE_MB", "10")) * 1024 * 1024
    )  # 兆字节 -> 字节
    log_backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))

    # 确保日志目录存在
    log_dir = Path(log_file_path).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_file_path,
        maxBytes=log_max_size,
        backupCount=log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    logging.info(
        f"日志文件: {log_file_path} (最大 {log_max_size // 1024 // 1024}MB, 保留 {log_backup_count} 份)"
    )


async def main() -> None:
    """主函数"""
    setup_logging()
    logger = logging.getLogger(__name__)

    try:
        config = get_config()
        logger.info(f"机器人 QQ: {config.bot_qq}")
        logger.info(f"超级管理员: {config.superadmin_qq}")
        logger.info(f"管理员 QQ: {config.admin_qqs}")
    except ValueError as e:
        logger.error(f"配置错误: {e}")
        sys.exit(1)

    # 初始化组件
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
    )
    faq_storage = FAQStorage()

    handler = MessageHandler(config, onebot, ai, faq_storage, task_storage)
    onebot.set_message_handler(handler.handle_message)

    logger.info("启动机器人...")

    try:
        await onebot.run_with_reconnect()
    except KeyboardInterrupt:
        logger.info("收到退出信号")
    finally:
        await onebot.disconnect()
        await ai.close()
        logger.info("机器人已停止")


def run() -> None:
    """运行入口"""
    asyncio.run(main())


if __name__ == "__main__":
    run()
