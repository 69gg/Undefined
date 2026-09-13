"""使用独立单文件令牌的 Runtime 下载路由。"""

from urllib.parse import quote

from aiohttp import web
from aiohttp.web_log import AccessLogger

from Undefined.onebot.file_store import (
    FILE_ROUTE_NAME,
    FileAuthorizationError,
    OneBotFileStore,
)


class FileAccessLogger(AccessLogger):
    """保留普通访问日志格式，专用文件路由只记录不带查询串的路径。"""

    def log(
        self, request: web.BaseRequest, response: web.StreamResponse, time: float
    ) -> None:
        if request.path.startswith("/api/v1/onebot/files/") or "token" in request.query:
            self.logger.info(
                "%s %s status=%d elapsed=%.3fs",
                request.method,
                request.path,
                response.status,
                time,
            )
        else:
            super().log(request, response, time)


def is_file_request(request: web.Request) -> bool:
    return request.match_info.route.name == FILE_ROUTE_NAME and request.method in {
        "GET",
        "HEAD",
    }


async def download(
    request: web.Request, store: OneBotFileStore | None
) -> web.StreamResponse:
    if store is None:
        return web.Response(status=404)
    try:
        async with store.acquire(
            request.match_info["file_id"], request.query.get("token", "")
        ) as entry:
            response = web.FileResponse(
                entry.path,
                headers={
                    "Content-Type": entry.content_type,
                    "Content-Disposition": f"attachment; filename*=UTF-8''{quote(entry.name, safe='')}",
                    "Cache-Control": "private, no-store",
                    "Referrer-Policy": "no-referrer",
                },
            )
            # FileResponse 在 prepare 中发送文件，不能在仅构造响应后释放读者租约。
            await response.prepare(request)
            await response.write_eof()
            return response
    except FileAuthorizationError as exc:
        return web.Response(status=exc.status)
