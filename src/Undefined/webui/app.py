import asyncio
import gzip as _gzip_mod
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from typing import Any, Awaitable, Callable
from aiohttp import web

from Undefined.config import load_webui_settings, get_config_manager, get_config
from .core import BotProcessController, SessionStore
from .routes import routes
from .utils import ensure_config_toml
from Undefined.utils.self_update import (
    GitUpdatePolicy,
    apply_git_update,
    format_update_result,
    restart_process,
)

# 初始化 WebUI 自身日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Undefined.webui")

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)

# ── gzip 压缩 ──

_GZIP_CONTENT_TYPES = frozenset(
    {
        "text/html",
        "text/css",
        "text/plain",
        "text/javascript",
        "application/javascript",
        "application/json",
        "image/svg+xml",
    }
)
_GZIP_FILE_EXTENSIONS = frozenset(
    {
        ".js",
        ".css",
        ".html",
        ".json",
        ".svg",
        ".xml",
        ".txt",
    }
)
_GZIP_MIN_BYTES = 512
_GZIP_MAX_BYTES = 2 * 1024 * 1024
_GZIP_MIME: dict[str, str] = {
    ".js": "application/javascript",
    ".css": "text/css",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".xml": "application/xml",
    ".txt": "text/plain; charset=utf-8",
}


def _gzip_compress(data: bytes) -> bytes | None:
    compressed = _gzip_mod.compress(data, compresslevel=6)
    return compressed if len(compressed) < len(data) else None


@web.middleware
async def gzip_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """对可压缩响应自动 gzip，覆盖 web.Response 和静态文件。"""
    response = await handler(request)

    if "gzip" not in request.headers.get("Accept-Encoding", ""):
        return response
    if response.headers.get("Content-Encoding"):
        return response

    # web.Response（HTML 模板、JSON API 等）
    if isinstance(response, web.Response):
        body = response.body
        if isinstance(body, bytes) and _GZIP_MIN_BYTES <= len(body) <= _GZIP_MAX_BYTES:
            ct = (response.content_type or "").split(";")[0].strip()
            if ct in _GZIP_CONTENT_TYPES:
                compressed = _gzip_compress(body)
                if compressed is not None:
                    response.body = compressed
                    response.headers["Content-Encoding"] = "gzip"
                    response.headers["Vary"] = "Accept-Encoding"
        return response

    # FileResponse（静态 JS/CSS 等）
    if isinstance(response, web.FileResponse):
        file_path: Path | None = getattr(response, "_path", None)
        if file_path is not None and file_path.suffix.lower() in _GZIP_FILE_EXTENSIONS:
            try:
                raw = await asyncio.to_thread(file_path.read_bytes)
            except OSError:
                return response
            if _GZIP_MIN_BYTES <= len(raw) <= _GZIP_MAX_BYTES:
                compressed = _gzip_compress(raw)
                if compressed is not None:
                    mime = _GZIP_MIME.get(
                        file_path.suffix.lower(), "application/octet-stream"
                    )
                    new_resp = web.Response(body=compressed, content_type=mime)
                    # 保留外层中间件已设置的 header（如安全头）
                    _skip = {
                        "content-length",
                        "content-type",
                        "content-encoding",
                        "transfer-encoding",
                    }
                    for key, value in response.headers.items():
                        if key.lower() not in _skip:
                            new_resp.headers.setdefault(key, value)
                    new_resp.headers["Content-Encoding"] = "gzip"
                    new_resp.headers["Vary"] = "Accept-Encoding"
                    return new_resp

    return response


@web.middleware
async def security_headers_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = exc
    response.headers.setdefault("Content-Security-Policy", CSP_POLICY)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


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
    logger.info("[WebUI] 后台任务已启动（热重载）")

    # If we restarted WebUI after an update and the bot was previously running,
    # auto-start it again.
    try:
        marker = Path("data/cache/pending_bot_autostart")
        if marker.exists():
            marker.unlink(missing_ok=True)
            bot: BotProcessController = app["bot"]
            await bot.start()
            logger.info("[WebUI] 检测到自动恢复标记，已尝试启动机器人进程")
    except Exception:
        logger.debug("[WebUI] 自动恢复机器人进程失败", exc_info=True)


async def on_shutdown(app: web.Application) -> None:
    bot: BotProcessController = app["bot"]
    status = bot.status()
    if not status.get("running"):
        logger.info("[WebUI] 正在关闭，无运行中的机器人进程")
        return
    logger.info("[WebUI] 正在关闭，准备停止机器人进程...")
    try:
        await asyncio.wait_for(bot.stop(), timeout=5)
    except asyncio.TimeoutError:
        logger.warning("[WebUI] 关闭超时：机器人进程停止失败")


async def on_cleanup(app: web.Application) -> None:
    await get_config_manager().stop_hot_reload()
    logger.info("[WebUI] 后台任务已停止")


def create_app(*, redirect_to_config_once: bool = False) -> web.Application:
    app = web.Application(middlewares=[gzip_middleware, security_headers_middleware])

    # 初始化核心组件
    app["bot"] = BotProcessController()
    app["session_store"] = SessionStore()

    # 配置 WebUI 设置热重载
    config_manager = get_config_manager()
    app["settings"] = load_webui_settings()

    # 一次性客户端重定向提示（由 index 处理）
    app["redirect_to_config_once"] = redirect_to_config_once

    def _on_config_change(config: Any, changes: dict[str, Any]) -> None:
        webui_keys = {"webui_url", "webui_port", "webui_password"}
        if any(key.startswith("webui.") for key in changes) or webui_keys.intersection(
            changes
        ):
            logger.info("[WebUI] 检测到 WebUI 配置变更，正在热重载设置...")
            app["settings"] = load_webui_settings()

    config_manager.subscribe(_on_config_change)

    # 路由
    app.add_routes(routes)

    # 静态资源
    static_dir = Path(__file__).parent / "static"
    app.router.add_static("/static", static_dir)

    # 生命周期
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    app.on_cleanup.append(on_cleanup)

    return app


def run() -> None:
    _init_webui_file_handler()

    # Git-based auto update (only for official origin/main).
    try:
        update_result = apply_git_update(GitUpdatePolicy())
        logger.info("[WebUI][自更新] %s", format_update_result(update_result))
        if update_result.updated and update_result.repo_root is not None:
            if update_result.uv_sync_attempted and not update_result.uv_synced:
                logger.warning(
                    "[WebUI][自更新] 代码已更新但 uv sync 失败，跳过自动重启（避免启动失败）"
                )
            else:
                logger.warning("[WebUI][自更新] 检测到更新，正在重启 WebUI...")
                restart_process(module="Undefined.webui", chdir=update_result.repo_root)
    except Exception as exc:
        logger.warning("[WebUI][自更新] 检查更新失败，将继续启动: %s", exc)

    created = ensure_config_toml()
    settings = load_webui_settings()

    app = create_app(redirect_to_config_once=created)

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
