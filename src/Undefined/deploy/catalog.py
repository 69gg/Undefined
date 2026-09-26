"""部署目录（唯一事实来源）。

集中定义：可部署服务清单、端口、默认值、以及 ``config.toml`` 的写入目标。
``generate`` / ``cli`` / ``state`` 都从这里取数据，避免同一事实散落多处。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# --------------------------------------------------------------------------- #
# 部署模式
# --------------------------------------------------------------------------- #

MODE_CONTAINER: Final[str] = "container"
MODE_HOST: Final[str] = "host"
DEPLOY_MODES: Final[tuple[str, ...]] = (MODE_CONTAINER, MODE_HOST)

#: 进程退出码，供 cli 与 commands 共用。
EXIT_OK: Final[int] = 0
EXIT_ERROR: Final[int] = 1

# --------------------------------------------------------------------------- #
# 运行态目录（相对仓库根，随 .gitignore 忽略）
# --------------------------------------------------------------------------- #

DEPLOY_DIR_NAME: Final[str] = "deploy"
STATE_FILE_NAME: Final[str] = "STATE.json"
ENV_FILE_NAME: Final[str] = ".env"
COMPOSE_FILE_NAME: Final[str] = "compose.yaml"
COMPOSE_PROJECT_NAME: Final[str] = "undefined-deploy"

# --------------------------------------------------------------------------- #
# 端口与绑定地址
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PortSpec:
    """一个需要发布的端口。

    ``env_var`` 由 :func:`port_env_var` / :func:`bind_env_var` 生成，
    模板与 ``.env`` 都用同一套命名，避免手写拼错。
    """

    key: str
    default: int
    label: str

    @property
    def env_var(self) -> str:
        return "UNDEFINED_DEPLOY_PORT_" + self.key.upper()

    @property
    def bind_env_var(self) -> str:
        return self.env_var + "_BIND"


#: 所有部署端口默认只绑定回环地址；需要远程访问时由用户显式改成 0.0.0.0。
DEFAULT_PORT_BIND: Final[str] = "127.0.0.1"

# --------------------------------------------------------------------------- #
# config.toml 写入目标
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ConfigTarget:
    """一条 ``config.toml`` 写入项。

    ``key`` 使用 ``apply_patch`` 支持的 dotted path；``rendered`` 用于让用户
    在 ``--dry-run`` / 汇总输出里看到将写入的值（敏感值由调用方脱敏）。
    """

    key: str
    rendered: str
    about: str


# --------------------------------------------------------------------------- #
# 服务清单
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Service:
    """一个可部署的依赖服务。

    ``key`` 是稳定标识：同时用于 CLI ``--with``、``STATE.json`` 与配置目标命名，
    因此不要为了改名而改名。``compose_fragment`` 指向包内模板文件名。
    """

    key: str
    label: str
    about: str
    compose_fragment: str
    ports: tuple[PortSpec, ...] = ()


NAPCAT: Final[Service] = Service(
    key="napcat",
    label="NapCat（OneBot V11 协议端）",
    about="QQ 消息收发的唯一通道，必需；QQ 登录需扫码。",
    compose_fragment="compose.napcat.yaml",
    ports=(
        PortSpec("napcat_ws", 3001, "OneBot 正向 WebSocket"),
        PortSpec("napcat_webui", 6099, "NapCat WebUI"),
    ),
)

SEARXNG: Final[Service] = Service(
    key="searxng",
    label="SearXNG（web_search）",
    about="内置 web_search 工具的后端；不部署时该工具不可用。",
    compose_fragment="compose.searxng.yaml",
    ports=(PortSpec("searxng", 8080, "SearXNG WebUI / JSON API"),),
)

FIRECRAWL: Final[Service] = Service(
    key="firecrawl",
    label="Firecrawl（firecrawl_search）",
    about="自带 api/playwright/redis/rabbitmq/postgres 五个容器，资源占用较高。",
    compose_fragment="compose.firecrawl.yaml",
    ports=(PortSpec("firecrawl", 3002, "Firecrawl API"),),
)

LXMUSIC2API: Final[Service] = Service(
    key="lxmusic2api",
    label="lxmusic2api（music.* 工具集）",
    about="上游无官方镜像，由本项目构建；取音频直链需自备 LX 自定义音源脚本。",
    compose_fragment="compose.lxmusic2api.yaml",
    ports=(PortSpec("lxmusic2api", 3000, "lxmusic2api API / Swagger"),),
)

#: 可选的额外服务（NapCat 必需，单独处理，不在此列）。
OPTIONAL_SERVICES: Final[tuple[Service, ...]] = (SEARXNG, FIRECRAWL, LXMUSIC2API)

#: NapCat 是必装项。
REQUIRED_SERVICES: Final[tuple[Service, ...]] = (NAPCAT,)

#: key -> Service 的索引，供 CLI 与生成器查询。
ALL_SERVICES: Final[dict[str, Service]] = {
    service.key: service for service in (*REQUIRED_SERVICES, *OPTIONAL_SERVICES)
}

# --------------------------------------------------------------------------- #
# 本体（Undefined）自身的端口；不是 Service，因为它随 mode 决定是否容器化
# --------------------------------------------------------------------------- #

BOT_PORTS: Final[tuple[PortSpec, ...]] = (
    PortSpec("bot_webui", 8787, "Undefined WebUI"),
    PortSpec("bot_api", 8788, "Runtime API"),
)

# --------------------------------------------------------------------------- #
# 默认值
# --------------------------------------------------------------------------- #

#: 部署脚本会写入的容器固定路径。
CONTAINER_REPO_ROOT: Final[str] = "/app"
CONTAINER_DOCKER_SOCK: Final[str] = "/var/run/docker.sock"
#: 未显式指定模型时输出给用户的提醒。
MODEL_REMINDER: Final[str] = (
    "config.toml 的 [models.*] 仍需填写模型端与 API Key，Bot 才能真正收发消息。"
)

DEFAULTS: Final[dict[str, object]] = {
    "mode": MODE_CONTAINER,
    "services": (),
    "nagaagent": False,
    "port_bind": DEFAULT_PORT_BIND,
}


def port_defaults() -> dict[str, int]:
    """返回全部端口的默认值（含本体端口）。"""
    ports: dict[str, int] = {}
    for spec in BOT_PORTS:
        ports[spec.key] = spec.default
    for service in ALL_SERVICES.values():
        for spec in service.ports:
            ports[spec.key] = spec.default
    return ports


def port_specs() -> dict[str, PortSpec]:
    """返回 key -> PortSpec 的索引（含本体端口）。"""
    specs: dict[str, PortSpec] = {}
    for spec in BOT_PORTS:
        specs[spec.key] = spec
    for service in ALL_SERVICES.values():
        for spec in service.ports:
            specs[spec.key] = spec
    return specs


def selected_service(key: str) -> Service:
    """按键取服务；未知名直接报错，避免静默忽略用户输入。"""
    try:
        return ALL_SERVICES[key]
    except KeyError as exc:
        known = ", ".join(sorted(ALL_SERVICES))
        raise KeyError(f"未知服务 {key!r}；可选：{known}") from exc


__all__ = [
    "ALL_SERVICES",
    "BOT_PORTS",
    "COMPOSE_FILE_NAME",
    "COMPOSE_PROJECT_NAME",
    "CONTAINER_DOCKER_SOCK",
    "CONTAINER_REPO_ROOT",
    "DEFAULT_PORT_BIND",
    "DEFAULTS",
    "DEPLOY_DIR_NAME",
    "DEPLOY_MODES",
    "ENV_FILE_NAME",
    "FIRECRAWL",
    "LXMUSIC2API",
    "MODE_CONTAINER",
    "MODE_HOST",
    "MODEL_REMINDER",
    "NAPCAT",
    "OPTIONAL_SERVICES",
    "PortSpec",
    "REQUIRED_SERVICES",
    "SEARXNG",
    "STATE_FILE_NAME",
    "Service",
    "ConfigTarget",
    "port_defaults",
    "port_specs",
    "selected_service",
]
