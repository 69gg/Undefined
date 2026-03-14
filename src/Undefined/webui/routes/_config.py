import asyncio
import tomllib
from pathlib import Path
from tempfile import NamedTemporaryFile

from aiohttp import web
from aiohttp.web_response import Response

from Undefined.config.loader import Config
from Undefined.config.loader import CONFIG_PATH, load_toml_data
from Undefined.config import get_config_manager
from ._shared import routes, check_auth
from ..utils import (
    read_config_source,
    validate_toml,
    validate_required_config,
    load_default_data,
    load_comment_map,
    merge_defaults,
    apply_patch,
    render_toml,
    sort_config,
    sync_config_file,
)


@routes.get("/api/v1/management/config")
@routes.get("/api/config")
async def get_config_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    return web.json_response(read_config_source())


@routes.post("/api/v1/management/config")
@routes.post("/api/config")
async def save_config_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    data = await request.json()
    content = data.get("content")
    if not content:
        return web.json_response({"error": "No content provided"}, status=400)
    valid, msg = validate_toml(content)
    if not valid:
        return web.json_response({"success": False, "error": msg}, status=400)
    try:
        CONFIG_PATH.write_text(content, encoding="utf-8")
        get_config_manager().reload()
        logic_valid, logic_msg = validate_required_config()
        return web.json_response(
            {
                "success": True,
                "message": "Saved",
                "warning": None if logic_valid else logic_msg,
            }
        )
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/v1/management/config/validate")
async def validate_config_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    content = str(data.get("content") or "")
    syntax_valid, syntax_message = validate_toml(content)
    strict_valid = False
    strict_message = ""
    if syntax_valid:
        with NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".toml", delete=False
        ) as f:
            f.write(content)
            f.flush()
            temp_path = Path(f.name)
        try:
            Config.load(temp_path, strict=True)
            strict_valid = True
            strict_message = "OK"
        except Exception as exc:
            strict_valid = False
            strict_message = str(exc)
        finally:
            temp_path.unlink(missing_ok=True)
    return web.json_response(
        {
            "success": syntax_valid and strict_valid,
            "syntax_valid": syntax_valid,
            "syntax_message": syntax_message,
            "strict_valid": strict_valid,
            "strict_message": strict_message,
        }
    )


@routes.get("/api/v1/management/config/summary")
@routes.get("/api/config/summary")
async def config_summary_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    data = load_toml_data()
    defaults = load_default_data()
    summary = merge_defaults(defaults, data)
    ordered = sort_config(summary)
    comments = load_comment_map()
    return web.json_response({"data": ordered, "comments": comments})


@routes.post("/api/v1/management/config/patch")
@routes.post("/api/patch")
async def config_patch_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    patch = body.get("patch")
    if not isinstance(patch, dict):
        return web.json_response({"error": "Invalid payload"}, status=400)

    source = read_config_source()
    try:
        data = tomllib.loads(source["content"]) if source["content"].strip() else {}
    except tomllib.TOMLDecodeError as exc:
        return web.json_response({"error": f"TOML parse error: {exc}"}, status=400)
    if not isinstance(data, dict):
        data = {}

    patched = apply_patch(data, patch)
    CONFIG_PATH.write_text(
        render_toml(patched, comments=load_comment_map()), encoding="utf-8"
    )
    get_config_manager().reload()
    validation_ok, validation_msg = validate_required_config()
    return web.json_response(
        {
            "success": True,
            "message": "Saved",
            "warning": None if validation_ok else validation_msg,
        }
    )


@routes.post("/api/v1/management/config/sync-template")
@routes.post("/api/config/sync-template")
async def sync_config_template_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    prune = request.query.get("prune") == "true"
    write = request.query.get("write", "true").lower() != "false"
    try:
        result = await asyncio.to_thread(sync_config_file, prune=prune, write=write)
        validation_ok = True
        validation_msg: str | None = None
        if write:
            await asyncio.to_thread(get_config_manager().reload)
            validation_ok, validation_msg = await asyncio.to_thread(
                validate_required_config
            )
        return web.json_response(
            {
                "success": True,
                "message": "Synced",
                "preview": not write,
                "added_paths": result.added_paths,
                "added_count": len(result.added_paths),
                "removed_paths": result.removed_paths,
                "removed_count": len(result.removed_paths),
                "warning": None if validation_ok else validation_msg,
            }
        )
    except FileNotFoundError as exc:
        return web.json_response({"success": False, "error": str(exc)}, status=404)
    except ValueError as exc:
        return web.json_response({"success": False, "error": str(exc)}, status=400)
    except Exception as exc:
        return web.json_response({"success": False, "error": str(exc)}, status=500)
