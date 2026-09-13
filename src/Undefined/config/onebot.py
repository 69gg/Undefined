"""OneBot 本地文件传输配置与单次投递快照。"""

from dataclasses import dataclass
from ipaddress import ip_address
import re
from typing import Any, Literal, cast

FileSendMode = Literal["local", "url", "stream"]
DEFAULT_FILE_SEND_MODE: FileSendMode = "stream"
DEFAULT_FILE_SEND_HOST = "127.0.0.1"


def parse_file_send_mode(value: Any) -> FileSendMode:
    mode = (
        str(value if value is not None else "").strip().lower()
        or DEFAULT_FILE_SEND_MODE
    )
    if mode not in {"local", "url", "stream"}:
        raise ValueError("onebot.file_send_mode 必须为 local、url 或 stream")
    return cast(FileSendMode, mode)


def parse_file_send_host(value: Any) -> str:
    host = str(value or "").strip() or DEFAULT_FILE_SEND_HOST
    if any(char in host for char in "/\\?#@%") or any(char.isspace() for char in host):
        raise ValueError(
            "onebot.file_send_host 必须为不带协议、端口、路径或作用域标识的主机地址"
        )
    if host.startswith("[") and host.endswith("]") and ":" in host:
        host = host[1:-1]
    try:
        return str(ip_address(host))
    except ValueError:
        pass
    try:
        ascii_host = host.rstrip(".").encode("idna").decode("ascii")
    except UnicodeError:
        ascii_host = ""
    if (
        not ascii_host
        or len(ascii_host) > 253
        or any(
            not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
            for label in ascii_host.split(".")
        )
    ):
        raise ValueError(
            "onebot.file_send_host 必须为 IPv4、IPv6 或域名，不包含协议、端口或路径"
        )
    return ascii_host


@dataclass(frozen=True)
class FileSendSettings:
    mode: FileSendMode = DEFAULT_FILE_SEND_MODE
    host: str = DEFAULT_FILE_SEND_HOST

    @classmethod
    def from_config(cls, config: Any) -> "FileSendSettings":
        return cls(
            parse_file_send_mode(getattr(config, "onebot_file_send_mode", None)),
            parse_file_send_host(getattr(config, "onebot_file_send_host", None)),
        )
