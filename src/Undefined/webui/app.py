import asyncio
import logging
import webbrowser
from pathlib import Path

from aiohttp import web

from Undefined.config import load_webui_settings
from .core import BotProcessController, SessionStore
from .routes import routes

# Setup logging for WebUI itself
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Undefined.webui")


async def on_shutdown(app: web.Application) -> None:
    logger.info("WebUI shutting down, stopping bot process...")
    bot: BotProcessController = app["bot"]
    await bot.stop()


def create_app() -> web.Application:
    app = web.Application()

    # Initialize core components
    app["bot"] = BotProcessController()
    app["session_store"] = SessionStore()
    app["settings"] = load_webui_settings()

    # Routes
    app.add_routes(routes)

    # Static files
    static_dir = Path(__file__).parent / "static"
    app.router.add_static("/static", static_dir)

    # Lifecycle
    app.on_shutdown.append(on_shutdown)

    return app


def run() -> None:
    settings = load_webui_settings()

    app = create_app()

    host = settings.url
    port = settings.port

    logger.info(f"Starting WebUI at http://{host}:{port}")
    if settings.using_default_password:
        logger.warning(
            "!!! USING DEFAULT PASSWORD !!! Please change 'webui.password' in config.toml"
        )

    # Auto open browser if local
    if host in ("127.0.0.1", "localhost", "0.0.0.0"):
        # run in a task to not block startup
        async def open_browser() -> None:
            await asyncio.sleep(1)
            target = "127.0.0.1" if host == "0.0.0.0" else host
            try:
                webbrowser.open(f"http://{target}:{port}")
            except Exception:
                pass

        # This is a bit hacky in pure aiohttp run_app, but we can just let user open it

    try:
        web.run_app(app, host=host, port=port, print=None)
    except KeyboardInterrupt:
        pass
    finally:
        # cleanup is handled by on_shutdown mostly, but ensures exit
        pass


if __name__ == "__main__":
    run()
