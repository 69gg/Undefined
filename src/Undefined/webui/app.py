import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from typing import Any
from aiohttp import web

from Undefined.config import load_webui_settings, get_config_manager, get_config
from .core import BotProcessController, SessionStore
from .routes import routes

# Setup logging for WebUI itself
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Undefined.webui")


def _init_webui_file_handler() -> None:
    root_logger = logging.getLogger()
    log_path = Path("logs/webui.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    for handler in root_logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            if Path(handler.baseFilename) == log_path:
                return

    try:
        config = get_config(strict=False)
        max_bytes = config.log_max_size
        backup_count = config.log_backup_count
    except Exception:
        max_bytes = 10 * 1024 * 1024
        backup_count = 5

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    root_logger.addHandler(file_handler)


async def on_startup(app: web.Application) -> None:
    get_config_manager().start_hot_reload()
    logger.info("[WebUI] Background tasks started (hot-reload)")


async def on_shutdown(app: web.Application) -> None:
    bot: BotProcessController = app["bot"]
    status = bot.status()
    if not status.get("running"):
        logger.info("WebUI shutting down, no bot process running")
        return
    logger.info("WebUI shutting down, stopping bot process...")
    try:
        await asyncio.wait_for(bot.stop(), timeout=5)
    except asyncio.TimeoutError:
        logger.warning("WebUI shutdown: bot stop timed out")


async def on_cleanup(app: web.Application) -> None:
    await get_config_manager().stop_hot_reload()
    logger.info("[WebUI] Background tasks stopped")


def create_app() -> web.Application:
    app = web.Application()

    # Initialize core components
    app["bot"] = BotProcessController()
    app["session_store"] = SessionStore()

    # Setup Hot Reload for WebUI settings
    config_manager = get_config_manager()
    app["settings"] = load_webui_settings()

    def _on_config_change(config: Any, changes: dict[str, Any]) -> None:
        webui_keys = {"webui_url", "webui_port", "webui_password"}
        if any(key.startswith("webui.") for key in changes) or webui_keys.intersection(
            changes
        ):
            logger.info("[WebUI] 检测到 WebUI 配置变更，正在热重载设置...")
            app["settings"] = load_webui_settings()

    config_manager.subscribe(_on_config_change)

    # Routes
    app.add_routes(routes)

    # Static files
    static_dir = Path(__file__).parent / "static"
    app.router.add_static("/static", static_dir)

    # Lifecycle
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    app.on_cleanup.append(on_cleanup)

    return app


def run() -> None:
    settings = load_webui_settings()
    _init_webui_file_handler()

    app = create_app()

    host = settings.url
    port = settings.port

    logger.info(f"Starting WebUI at http://{host}:{port}")
    if settings.using_default_password:
        logger.warning(
            "!!! USING DEFAULT PASSWORD !!! Please change 'webui.password' in config.toml"
        )

    try:
        web.run_app(
            app,
            host=host,
            port=port,
            print=None,
            shutdown_timeout=1.0,
        )
    except KeyboardInterrupt:
        pass
    finally:
        # cleanup is handled by on_shutdown mostly, but ensures exit
        pass


if __name__ == "__main__":
    run()
