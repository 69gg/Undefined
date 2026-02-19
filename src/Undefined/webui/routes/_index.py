import json

from aiohttp import web
from aiohttp.web_response import Response

from Undefined import __version__
from ._shared import routes, TEMPLATE_DIR, get_settings


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

    lang = request.cookies.get("undefined_lang", "zh")
    theme = request.cookies.get("undefined_theme", "light")
    redirect_to_config = bool(request.app.get("redirect_to_config_once"))

    initial_state = {
        "using_default_password": settings.using_default_password,
        "config_exists": settings.config_exists,
        "redirect_to_config": redirect_to_config,
        "version": __version__,
        "license": license_text,
        "lang": lang,
        "theme": theme,
    }
    if redirect_to_config:
        request.app["redirect_to_config_once"] = False

    initial_state_json = json.dumps(initial_state).replace("</", "<\\/")
    html = html.replace("__INITIAL_STATE__", initial_state_json)
    html = html.replace("__INITIAL_VIEW__", json.dumps("landing"))
    return web.Response(text=html, content_type="text/html")
