import json

from aiohttp import web
from aiohttp.web_response import Response

from Undefined import __version__
from ._shared import (
    REDIRECT_TO_CONFIG_ONCE_APP_KEY,
    TEMPLATE_DIR,
    get_settings,
    routes,
)


@routes.get("/")
async def index_handler(request: web.Request) -> Response:
    settings = get_settings(request)
    html_file = TEMPLATE_DIR / "index.html"
    if not html_file.exists():
        return web.Response(text="Index template not found", status=500)

    html = html_file.read_text(encoding="utf-8")
    license_text = ""
    from pathlib import Path

    license_file = Path("LICENSE")
    if license_file.exists():
        license_text = license_file.read_text(encoding="utf-8")

    query_lang = str(request.query.get("lang") or "").strip().lower()
    query_theme = str(request.query.get("theme") or "").strip().lower()
    query_view = str(request.query.get("view") or "").strip().lower()
    query_tab = str(request.query.get("tab") or "").strip().lower()
    query_client = str(request.query.get("client") or "").strip().lower()
    query_return_to = str(request.query.get("return_to") or "").strip()

    lang = (
        query_lang
        if query_lang in {"zh", "en"}
        else request.cookies.get("undefined_lang", "zh")
    )
    theme = (
        query_theme
        if query_theme in {"light", "dark"}
        else request.cookies.get("undefined_theme", "light")
    )
    initial_view = query_view if query_view in {"landing", "app"} else "landing"
    initial_tab = query_tab or "overview"
    launcher_mode = query_client in {"native", "app"}
    redirect_to_config = bool(request.app.get(REDIRECT_TO_CONFIG_ONCE_APP_KEY, False))

    initial_state = {
        "using_default_password": settings.using_default_password,
        "config_exists": settings.config_exists,
        "redirect_to_config": redirect_to_config,
        "version": __version__,
        "license": license_text,
        "lang": lang,
        "theme": theme,
        "initial_tab": initial_tab,
        "launcher_mode": launcher_mode,
        "return_to": query_return_to if launcher_mode else "",
    }
    if redirect_to_config:
        request.app[REDIRECT_TO_CONFIG_ONCE_APP_KEY] = False

    initial_state_json = json.dumps(initial_state).replace("</", "<\\/")
    html = html.replace("__INITIAL_STATE__", initial_state_json)
    html = html.replace("__INITIAL_VIEW__", json.dumps(initial_view))
    response = web.Response(text=html, content_type="text/html")
    if query_lang in {"zh", "en"}:
        response.set_cookie(
            "undefined_lang",
            lang,
            max_age=30 * 24 * 60 * 60,
            samesite="Lax",
        )
    if query_theme in {"light", "dark"}:
        response.set_cookie(
            "undefined_theme",
            theme,
            max_age=30 * 24 * 60 * 60,
            samesite="Lax",
        )
    return response
