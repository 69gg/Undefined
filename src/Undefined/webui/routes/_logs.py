import asyncio
import re
import tomllib
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.web_response import Response

from Undefined.config.loader import CONFIG_PATH
from ._shared import routes, check_auth
from ..utils import tail_file


def _resolve_log_path() -> Path:
    log_path = Path("logs/bot.log")
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "rb") as f:
                cfg = tomllib.load(f)
            path_str = cfg.get("logging", {}).get("file_path")
            if path_str:
                log_path = Path(path_str)
    except Exception:
        pass
    return log_path


def _resolve_webui_log_path() -> Path:
    return Path("logs/webui.log")


def _is_log_file(path: Path) -> bool:
    name = path.name
    if ".log" not in name:
        return False
    return not name.lower().endswith((".tar", ".tar.gz", ".tgz"))


def _list_log_files(base_path: Path) -> list[Path]:
    files = [base_path]
    if base_path.parent.exists():
        prefix = f"{base_path.name}."
        for candidate in base_path.parent.glob(f"{base_path.name}.*"):
            suffix = candidate.name[len(prefix) :]
            if suffix.isdigit():
                files.append(candidate)

    def _sort_key(path: Path) -> tuple[int, str]:
        if path.name == base_path.name:
            return (0, "")
        match = re.search(r"\.([0-9]+)$", path.name)
        if match:
            return (1, match.group(1).zfill(6))
        return (2, path.name)

    return sorted(files, key=_sort_key)


def _list_all_log_files(log_dir: Path) -> list[Path]:
    if not log_dir.exists():
        return []
    files = [p for p in log_dir.glob("*.log*") if _is_log_file(p)]
    files.sort(key=lambda p: p.name)
    return files


def _resolve_log_file(base_path: Path, file_name: str | None) -> Path | None:
    if not file_name:
        return base_path
    return next((p for p in _list_log_files(base_path) if p.name == file_name), None)


def _resolve_any_log_file(log_dir: Path, file_name: str | None) -> Path | None:
    if not file_name:
        return None
    return next((p for p in _list_all_log_files(log_dir) if p.name == file_name), None)


@routes.get("/api/logs")
async def logs_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    lines = max(1, min(int(request.query.get("lines", "200")), 2000))
    log_type = request.query.get("type", "bot")
    file_name = request.query.get("file")
    if log_type == "webui":
        target_path = _resolve_log_file(_resolve_webui_log_path(), file_name)
    elif log_type == "all":
        target_path = _resolve_any_log_file(Path("logs"), file_name)
    else:
        target_path = _resolve_log_file(_resolve_log_path(), file_name)
    if target_path is None:
        return web.json_response({"error": "Log file not found"}, status=404)
    return web.Response(text=tail_file(target_path, lines))


@routes.get("/api/logs/files")
async def logs_files_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    log_type = request.query.get("type", "bot")
    if log_type == "webui":
        log_path = _resolve_webui_log_path()
        files_list = _list_log_files(log_path)
        current_name = log_path.name
    elif log_type == "all":
        files_list = _list_all_log_files(Path("logs"))
        current_name = ""
    else:
        log_path = _resolve_log_path()
        files_list = _list_log_files(log_path)
        current_name = log_path.name

    files: list[dict[str, Any]] = []
    for path in files_list:
        try:
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "size": stat.st_size,
                    "modified": int(stat.st_mtime),
                    "current": path.name == current_name,
                    "exists": True,
                }
            )
        except FileNotFoundError:
            files.append(
                {
                    "name": path.name,
                    "size": 0,
                    "modified": 0,
                    "current": path.name == current_name,
                    "exists": False,
                }
            )
    return web.json_response({"files": files, "current": current_name})


@routes.get("/api/logs/stream")
async def logs_stream_handler(request: web.Request) -> web.StreamResponse:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    lines = max(1, min(int(request.query.get("lines", "200")), 2000))
    log_type = request.query.get("type", "bot")
    if log_type == "all":
        return web.json_response(
            {"error": "Streaming only supports bot/webui logs"}, status=400
        )
    log_path = _resolve_webui_log_path() if log_type == "webui" else _resolve_log_path()
    file_name = request.query.get("file")
    if file_name and file_name != log_path.name:
        return web.json_response(
            {"error": "Streaming only supports current log"}, status=400
        )

    resp = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await resp.prepare(request)
    last_payload: str | None = None
    try:
        while True:
            if request.transport is None or request.transport.is_closing():
                break
            payload = tail_file(log_path, lines)
            if payload != last_payload:
                data = "\n".join(f"data: {line}" for line in payload.splitlines())
                await resp.write((data + "\n\n").encode("utf-8"))
                last_payload = payload
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    except (ConnectionResetError, RuntimeError):
        pass
    finally:
        try:
            await resp.write_eof()
        except Exception:
            pass
    return resp
