import ipaddress
from urllib.parse import urlsplit


def normalize_origin(origin: str) -> str:
    text = str(origin or "").strip().rstrip("/")
    if not text:
        return ""
    return text.lower()


def _is_loopback_host(host: str) -> bool:
    text = str(host or "").strip().lower()
    if not text:
        return False
    if text == "localhost":
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def _is_loopback_http_origin(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    return _is_loopback_host(parsed.hostname or "")


def is_allowed_cors_origin(
    origin: str,
    *,
    configured_host: str = "",
    configured_port: int | None = None,
    extra_origins: set[str] | None = None,
) -> bool:
    normalized = normalize_origin(origin)
    if not normalized:
        return False

    allowed = {normalize_origin(item) for item in extra_origins or set() if item}
    host = str(configured_host or "").strip()
    if host:
        for scheme in ("http", "https"):
            allowed.add(normalize_origin(f"{scheme}://{host}"))
            if configured_port is not None:
                allowed.add(normalize_origin(f"{scheme}://{host}:{configured_port}"))

    if normalized in allowed:
        return True
    if normalized == "tauri://localhost":
        return True
    return _is_loopback_http_origin(normalized)
