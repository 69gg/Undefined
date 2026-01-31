"""程序入口"""

import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
from rich.logging import RichHandler
from rich.console import Console

from Undefined.ai import AIClient
from Undefined.config import get_config
from Undefined.context import RequestContextFilter
from Undefined.faq import FAQStorage
from Undefined.handlers import MessageHandler
from Undefined.memory import MemoryStorage
from Undefined.scheduled_task_storage import ScheduledTaskStorage
from Undefined.end_summary_storage import EndSummaryStorage
from Undefined.onebot import OneBotClient


def setup_logging() -> None:
    """设置日志（控制台 + 文件轮转）"""
    load_dotenv()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level, logging.INFO)

    # 日志格式
    # 丰富日志处理器会自动处理时间戳、级别等，所以我们减短格式
    log_format = "%(name)s: %(message)s"
    file_log_format = "%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s"  # Modified to include request_id
    file_formatter = logging.Formatter(file_log_format)

    # 根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 控制台处理器（使用 Rich）
    console = Console(force_terminal=True)
    console_handler = RichHandler(
        level=level,
        console=console,
        show_time=True,
        show_path=True,
        markup=True,
        rich_tracebacks=True,
    )
    console_handler.setFormatter(logging.Formatter(log_format))
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
    file_handler.setFormatter(file_formatter)
    file_handler.addFilter(RequestContextFilter())  # 添加请求上下文过滤器
    root_logger.addHandler(file_handler)

    logging.info(
        f"[bold cyan][启动][/bold cyan] 日志系统初始化完成。级别: [yellow]{log_level}[/yellow], 文件: [green]{log_file_path}[/green] "
        f"(最大 [magenta]{log_max_size // 1024 // 1024}[/magenta]MB, 保留 [magenta]{log_backup_count}[/magenta] 份)"
    )


async def main() -> None:
    """主函数"""
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("[启动] 正在初始化 Undefined 机器人...")

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
        )
        faq_storage = FAQStorage()

        handler = MessageHandler(config, onebot, ai, faq_storage, task_storage)
        onebot.set_message_handler(handler.handle_message)
        logger.info("[初始化] 核心组件加载完成")
    except Exception as e:
        logger.exception(f"[初始化错误] 组件初始化期间发生异常: {e}")
        sys.exit(1)

    logger.info("[启动] 机器人已准备就绪，开始连接 OneBot 服务...")

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
        logger.info("[退出] 机器人已停止运行")


def run() -> None:
    """运行入口"""
    asyncio.run(main())


if __name__ == "__main__":
    run()
