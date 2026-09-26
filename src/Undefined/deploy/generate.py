"""纯生成层：把「部署选择」变成 compose 文件、服务配置与 config.toml 写入计划。

本模块不触碰 docker、不落盘，只做字符串/结构生成，便于单测。
落盘与执行在 ``runner`` 里。
"""

from __future__ import annotations

import json
import secrets
import string
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Final, Iterable

import yaml

from Undefined.deploy import catalog, images, nagaagent
from Undefined.deploy.config_patch import PatchPlan
from Undefined.deploy.state import DeployLayout

#: 本体在 compose 里的服务名（与 compose.bot.yaml 一致）。
BOT_SERVICE_NAME: Final[str] = "undefined-bot"
#: NapCat 在 compose 里的服务名（与 compose.napcat.yaml 一致）。
NAPCAT_SERVICE_NAME: Final[str] = "napcat"
#: 本体容器内的工作目录（与 compose.bot.yaml 的 working_dir 一致）。
CONTAINER_REPO_PATH: Final[str] = "/data/Undefined"

TEMPLATE_PACKAGE = "Undefined.deploy.templates"

#: 模板里用于占位替换的标记。
SEARXNG_SECRET_PLACEHOLDER = "__UNDEFINED_DEPLOY_SEARXNG_SECRET__"
SEARXNG_BASE_URL_PLACEHOLDER = "__UNDEFINED_DEPLOY_SEARXNG_BASE_URL__"
LXMUSIC2API_KEY_PLACEHOLDER = "__UNDEFINED_DEPLOY_LXMUSIC2API_KEY__"
NAPCAT_WS_PORT_PLACEHOLDER = "__UNDEFINED_DEPLOY_NAPCAT_WS_PORT__"
NAPCAT_WS_TOKEN_PLACEHOLDER = "__UNDEFINED_DEPLOY_NAPCAT_WS_TOKEN__"

#: NapCat 生成物：镜像入口每次启动都会 `cp /app/templates/$MODE.json <配置>`，
#: 所以我们用自己的 ws.json 覆盖镜像模板目录，让端口与 token 每次自动生效。
NAPCAT_WS_TEMPLATE = "napcat.ws.json"
#: 落盘到 deploy/napcat/ 的文件名；必须与 compose 的挂载源一致。
NAPCAT_WS_ARTIFACT = "ws.json"
NAPCAT_TEMPLATE_DIR = "/app/templates"

#: 生成 compose 时允许出现的顶层键；模板里写了别的键会直接报错。
ALLOWED_COMPOSE_TOP_KEYS = frozenset({"services", "volumes", "networks", "secrets"})

#: 默认「已知不安全」的占位值：命中这些值就重新生成随机凭据。
PLACEHOLDER_SECRETS = frozenset({"", "changeme", "replace-with-your-key", "napcat"})

#: 随机凭据长度。
NAPCAT_TOKEN_BYTES = 24
WEBUI_PASSWORD_BYTES = 18
API_AUTH_KEY_BYTES = 24
SEARXNG_SECRET_BYTES = 32
LXMUSIC2API_KEY_BYTES = 32
POSTGRES_PASSWORD_BYTES = 24
BULL_AUTH_KEY_BYTES = 24

#: 需要写入 deploy/.env 的变量名前缀。
IMAGE_ENV_PREFIX = "UNDEFINED_DEPLOY_"

#: 挂进本体容器的宿主机 Docker socket（DooD）。
DOCKER_SOCKET_ENV = "UNDEFINED_DEPLOY_DOCKER_SOCKET"


class GenerateError(RuntimeError):
    """生成阶段的可预期错误（模板缺失、模板内容不合法等）。"""


@dataclass(frozen=True, slots=True)
class GenerateContext:
    """一次 ``up`` 的全部输入。"""

    repo: Path
    layout: DeployLayout
    mode: str
    services: tuple[str, ...] = ()
    nagaagent: bool = False
    ports: dict[str, int] = field(default_factory=dict)
    port_bind: str = catalog.DEFAULT_PORT_BIND
    image_owner: str = images.DEFAULT_IMAGE_OWNER
    version: str = images.DEV_VERSION
    docker_socket: str = catalog.CONTAINER_DOCKER_SOCK
    #: 上次生成的 ``.env``（键值均为字符串）；用于复用凭据。
    previous_env: dict[str, str] = field(default_factory=dict)
    #: 现有 ``config.toml`` 解析结果；用于复用用户已配置的凭据、避免覆盖。
    existing_config: dict[str, Any] = field(default_factory=dict)

    def port(self, key: str) -> int:
        specs = catalog.port_specs()
        if key in specs:
            return self.ports.get(key, specs[key].default)
        raise GenerateError(f"未知端口键 {key!r}")


@dataclass(frozen=True, slots=True)
class GeneratedConfiguration:
    """生成结果（内存态，尚未写盘）。"""

    env: dict[str, str]
    compose_text: str
    patch_plan: PatchPlan
    searxng_settings: str | None = None
    firecrawl_env: str | None = None
    napcat_ws_config: str = ""
    lxmusic2api_config: str | None = None
    napcat_ws_token: str = ""
    websocket_url: str = ""


# --------------------------------------------------------------------------- #
# 模板读取
# --------------------------------------------------------------------------- #


def read_template(name: str) -> str:
    """读取包内模板；缺失或为空直接报错，避免生成半成品。"""
    try:
        resource = resources.files(TEMPLATE_PACKAGE).joinpath(name)
        text = resource.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise GenerateError(f"缺少部署模板 {name}") from exc
    if not text.strip():
        raise GenerateError(f"部署模板 {name} 为空")
    return text


# --------------------------------------------------------------------------- #
# 随机凭据
# --------------------------------------------------------------------------- #


def random_secret(length: int, *, alphabet: str | None = None) -> str:
    """生成随机凭据（默认大小写字母+数字，足够避免 TOML/YAML/URL 转义问题）。"""
    chars = alphabet or (string.ascii_letters + string.digits)
    return "".join(secrets.choice(chars) for _ in range(length))


def reuse_or_generate(
    previous: str | None, *, length: int, alphabet: str | None = None
) -> str:
    """沿用已有凭据；没有或不安全占位值时生成新的。

    ``up`` 幂等性的关键：重复部署不会把已生效的 token/密码换掉。
    """
    if previous is not None:
        candidate = previous.strip()
        if candidate and candidate not in PLACEHOLDER_SECRETS:
            return candidate
    return random_secret(length, alphabet=alphabet)


# --------------------------------------------------------------------------- #
# .env 与 compose
# --------------------------------------------------------------------------- #


def compose_service_urls(ctx: GenerateContext) -> dict[str, str]:
    """按模式给出各服务的 base_url 映射。

    容器模式下用 compose 服务名直连，避免绕宿主机网关多一跳；
    host 模式下本体在宿主机上，只能走发布的回环端口。
    """
    mode = ctx.mode
    if mode == catalog.MODE_CONTAINER:
        return {
            "searxng": "http://searxng:8080",
            "firecrawl": "http://firecrawl-api:3002",
            "lxmusic2api": "http://lxmusic2api:3000",
        }
    if mode == catalog.MODE_HOST:
        # 本体在宿主机上，只能走发布端口——必须用**覆盖后**的端口，
        # 否则用户 --port 之后就再也连不上（旧实现取的是默认值）。
        host = ctx.port_bind
        return {
            "searxng": f"http://{host}:{ctx.port('searxng')}",
            "firecrawl": f"http://{host}:{ctx.port('firecrawl')}",
            "lxmusic2api": f"http://{host}:{ctx.port('lxmusic2api')}",
        }
    raise GenerateError(f"未知部署模式 {mode!r}")


def _websocket_url(ctx: GenerateContext) -> str:
    """本体连接协议端的地址（NapCat 作正向 WS 服务端）。"""
    port = ctx.port("napcat_ws")
    if ctx.mode == catalog.MODE_CONTAINER:
        return f"ws://napcat:{port}"
    return f"ws://{catalog.DEFAULT_PORT_BIND}:{port}"


def build_env(ctx: GenerateContext) -> dict[str, str]:
    """构造 ``deploy/.env``：镜像引用、端口/绑定、以及全部凭据。"""
    previous = ctx.previous_env
    existing = ctx.existing_config

    def prev(name: str) -> str | None:
        return previous.get(name)

    env: dict[str, str] = {
        f"{IMAGE_ENV_PREFIX}BOT_IMAGE": images.bot_image(
            ctx.image_owner, ctx.version
        ).reference,
        f"{IMAGE_ENV_PREFIX}NAPCAT_IMAGE": images.NAPCAT_IMAGE,
        f"{IMAGE_ENV_PREFIX}SEARXNG_IMAGE": images.SEARXNG_IMAGE,
        f"{IMAGE_ENV_PREFIX}FIRECRAWL_IMAGE": images.FIRECRAWL_IMAGE,
        f"{IMAGE_ENV_PREFIX}FIRECRAWL_PLAYWRIGHT_IMAGE": (
            images.FIRECRAWL_PLAYWRIGHT_IMAGE
        ),
        f"{IMAGE_ENV_PREFIX}FIRECRAWL_POSTGRES_IMAGE": (
            images.FIRECRAWL_POSTGRES_IMAGE
        ),
        f"{IMAGE_ENV_PREFIX}FIRECRAWL_REDIS_IMAGE": images.FIRECRAWL_REDIS_IMAGE,
        f"{IMAGE_ENV_PREFIX}FIRECRAWL_RABBITMQ_IMAGE": images.FIRECRAWL_RABBITMQ_IMAGE,
        f"{IMAGE_ENV_PREFIX}LXMUSIC2API_IMAGE": images.lxmusic2api_image(
            ctx.image_owner, images.LXMUSIC2API_UPSTREAM_SHA
        ).reference,
        f"{IMAGE_ENV_PREFIX}FIRECRAWL_API_CPUS": images.FIRECRAWL_API_CPUS,
        f"{IMAGE_ENV_PREFIX}FIRECRAWL_API_MEMORY": images.FIRECRAWL_API_MEMORY,
        f"{IMAGE_ENV_PREFIX}FIRECRAWL_PLAYWRIGHT_CPUS": (
            images.FIRECRAWL_PLAYWRIGHT_CPUS
        ),
        f"{IMAGE_ENV_PREFIX}FIRECRAWL_PLAYWRIGHT_MEMORY": (
            images.FIRECRAWL_PLAYWRIGHT_MEMORY
        ),
        f"{IMAGE_ENV_PREFIX}FIRECRAWL_INTERNAL_PORT": "3002",
        DOCKER_SOCKET_ENV: ctx.docker_socket,
        # NapCat 挂载目录属主，交给容器 entrypoint 做 gosu 降权
        "UNDEFINED_DEPLOY_NAPCAT_UID": str(_current_uid()),
        "UNDEFINED_DEPLOY_NAPCAT_GID": str(_current_gid()),
        "UNDEFINED_DEPLOY_LXMUSIC2API_UID": str(_current_uid()),
        "UNDEFINED_DEPLOY_LXMUSIC2API_GID": str(_current_gid()),
    }

    # 端口与绑定：默认只绑回环，远程访问需显式改 --port-bind
    for key, spec in catalog.port_specs().items():
        if key not in _selected_port_keys(ctx):
            continue
        env[spec.env_var] = str(ctx.port(key))
        env[spec.bind_env_var] = ctx.port_bind

    # 凭据：优先复用 .env，其次复用 config.toml 里已生效的值，最后生成随机值
    env["UNDEFINED_DEPLOY_NAPCAT_WEBUI_TOKEN"] = reuse_or_generate(
        prev("UNDEFINED_DEPLOY_NAPCAT_WEBUI_TOKEN"), length=NAPCAT_TOKEN_BYTES
    )
    env["UNDEFINED_DEPLOY_NAPCAT_WS_TOKEN"] = reuse_or_generate(
        prev("UNDEFINED_DEPLOY_NAPCAT_WS_TOKEN"), length=NAPCAT_TOKEN_BYTES
    )
    env["UNDEFINED_DEPLOY_WEBUI_PASSWORD"] = reuse_or_generate(
        prev("UNDEFINED_DEPLOY_WEBUI_PASSWORD")
        or _config_str(existing, "webui.password"),
        length=WEBUI_PASSWORD_BYTES,
    )
    env["UNDEFINED_DEPLOY_API_AUTH_KEY"] = reuse_or_generate(
        prev("UNDEFINED_DEPLOY_API_AUTH_KEY") or _config_str(existing, "api.auth_key"),
        length=API_AUTH_KEY_BYTES,
    )
    env["UNDEFINED_DEPLOY_SEARXNG_SECRET"] = reuse_or_generate(
        prev("UNDEFINED_DEPLOY_SEARXNG_SECRET"), length=SEARXNG_SECRET_BYTES
    )
    env["UNDEFINED_DEPLOY_FIRECRAWL_POSTGRES_USER"] = "postgres"
    env["UNDEFINED_DEPLOY_FIRECRAWL_POSTGRES_DB"] = "postgres"
    env["UNDEFINED_DEPLOY_FIRECRAWL_POSTGRES_PASSWORD"] = reuse_or_generate(
        prev("UNDEFINED_DEPLOY_FIRECRAWL_POSTGRES_PASSWORD"),
        length=POSTGRES_PASSWORD_BYTES,
    )
    env["UNDEFINED_DEPLOY_FIRECRAWL_BULL_AUTH_KEY"] = reuse_or_generate(
        prev("UNDEFINED_DEPLOY_FIRECRAWL_BULL_AUTH_KEY"), length=BULL_AUTH_KEY_BYTES
    )
    env["UNDEFINED_DEPLOY_LXMUSIC2API_KEY"] = reuse_or_generate(
        prev("UNDEFINED_DEPLOY_LXMUSIC2API_KEY"), length=LXMUSIC2API_KEY_BYTES
    )

    # 服务自身读取的变量：必须与端口映射保持一致
    env["SEARXNG_BASE_URL"] = _searxng_base_url(ctx)
    env["UNDEFINED_DEPLOY_SEARXNG_BASE_URL"] = env["SEARXNG_BASE_URL"]

    return env


def _searxng_base_url(ctx: GenerateContext) -> str:
    port = ctx.port("searxng")
    if ctx.port_bind in ("0.0.0.0", "::"):
        host = "localhost"
    else:
        host = ctx.port_bind
    return f"http://{host}:{port}"


def _selected_port_keys(ctx: GenerateContext) -> set[str]:
    """需要发布的端口键：NapCat + 已选服务的端口（本体端口仅在容器模式发布）。"""
    keys: set[str] = set()
    if ctx.mode == catalog.MODE_CONTAINER:
        keys.update(spec.key for spec in catalog.BOT_PORTS)
    keys.update(spec.key for spec in catalog.NAPCAT.ports)
    for key in ctx.services:
        keys.update(spec.key for spec in catalog.selected_service(key).ports)
    return keys


def _current_uid() -> int:
    import os

    return os.getuid() if hasattr(os, "getuid") else 0


def _current_gid() -> int:
    import os

    return os.getgid() if hasattr(os, "getgid") else 0


def render_env(env: dict[str, str]) -> str:
    """渲染 ``.env``：``KEY=value`` 每行一条，不引号、不转义（值由我们生成）。"""
    lines = [
        "# 由 `uv run deploy up` 生成，请勿手工编辑：下次 up 会按选择重新生成。",
        "# 含凭据，文件权限 0600。",
        "",
    ]
    for key in sorted(env):
        lines.append(f"{key}={env[key]}")
    return "\n".join(lines) + "\n"


def compose_fragment_names(ctx: GenerateContext) -> tuple[str, ...]:
    """按顺序给出需要合并的模板片段。"""
    names = ["compose.base.yaml"]
    if ctx.mode == catalog.MODE_CONTAINER:
        names.append("compose.bot.yaml")
    names.append(catalog.NAPCAT.compose_fragment)
    for key in ctx.services:
        names.append(catalog.selected_service(key).compose_fragment)
    return tuple(names)


def load_compose_fragments(names: Iterable[str]) -> dict[str, Any]:
    """解析并合并模板片段（services / volumes / networks）。

    片段里的模板标记（``${VAR}``）原样保留，交由 ``docker compose`` 做变量替换，
    这样 ``.env`` 里变量名拼错会直接报错而不是静默取默认值。
    """
    merged: dict[str, Any] = {"services": {}, "volumes": {}, "networks": {}}
    for name in names:
        raw = read_template(name)
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise GenerateError(f"模板 {name} 不是合法 YAML：{exc}") from exc
        if not isinstance(data, dict):
            raise GenerateError(f"模板 {name} 的顶层必须是映射")

        unknown = set(data) - ALLOWED_COMPOSE_TOP_KEYS
        if unknown:
            raise GenerateError(
                f"模板 {name} 含不支持的顶层键 {sorted(unknown)}；"
                f"只允许 {sorted(ALLOWED_COMPOSE_TOP_KEYS)}"
            )

        for section in ("services", "volumes", "networks"):
            block = data.get(section) or {}
            if not isinstance(block, dict):
                raise GenerateError(f"模板 {name} 的 {section} 必须是映射")
            target = merged[section]
            duplicates = set(block) & set(target)
            if duplicates:
                raise GenerateError(
                    f"模板 {name} 与其它片段重复定义 {section}: {sorted(duplicates)}"
                )
            target.update(block)
    return merged


def render_compose(fragments: dict[str, Any], *, project_name: str) -> str:
    """渲染最终 ``compose.yaml``。"""
    payload = {"name": project_name, **fragments}
    text = yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=100,
    )
    header = (
        "# 由 `uv run deploy up` 生成，请勿手工编辑：\n"
        "# 修改部署选择请重跑 up，或调整 "
        f"{TEMPLATE_PACKAGE} 下的模板。\n"
        f"# 变量取值见同目录 {catalog.ENV_FILE_NAME}。\n\n"
    )
    return header + text


# --------------------------------------------------------------------------- #
# 各服务配置
# --------------------------------------------------------------------------- #


def render_searxng_settings(ctx: GenerateContext, env: dict[str, str]) -> str:
    text = read_template("searxng.settings.yml")
    return text.replace(
        SEARXNG_SECRET_PLACEHOLDER, env["UNDEFINED_DEPLOY_SEARXNG_SECRET"]
    ).replace(SEARXNG_BASE_URL_PLACEHOLDER, env["UNDEFINED_DEPLOY_SEARXNG_BASE_URL"])


def render_napcat_ws_config(ctx: GenerateContext, env: dict[str, str]) -> str:
    """生成 NapCat 的正向 WS 配置（含端口与 token）。

    容器内固定监听 ``NAPCAT_WS_CONTAINER_PORT``；挂到 ``/app/templates/ws.json``
    后，镜像入口每次启动都会把它拷成 ``onebot11.json``，因此 token 不会像
    「启动后补写宿主文件」那样被下一次重启抹掉。
    """
    text = read_template(NAPCAT_WS_TEMPLATE)
    rendered = text.replace(
        NAPCAT_WS_PORT_PLACEHOLDER, str(catalog.container_port("napcat_ws"))
    ).replace(NAPCAT_WS_TOKEN_PLACEHOLDER, env["UNDEFINED_DEPLOY_NAPCAT_WS_TOKEN"])
    try:
        json.loads(rendered)
    except json.JSONDecodeError as exc:  # pragma: no cover - 模板写坏时立即暴露
        raise GenerateError(f"近生成的 NapCat WS 配置不是合法 JSON：{exc}") from exc
    return rendered


def render_firecrawl_env(env: dict[str, str]) -> str:
    """Firecrawl api/postgres 的 env_file 内容。

    只写必要变量：上游 compose 里大量可选项留空会让容器拿到空字符串，
    不如不写、让镜像内默认值生效。``USE_DB_AUTHENTICATION=false`` 时上游
    明确不校验任何 key（自托管属可信网络方案）。
    """
    lines = [
        "# 由 `uv run deploy up` 生成，请勿手工编辑。",
        "USE_DB_AUTHENTICATION=false",
        "POSTGRES_USER=" + env["UNDEFINED_DEPLOY_FIRECRAWL_POSTGRES_USER"],
        "POSTGRES_PASSWORD=" + env["UNDEFINED_DEPLOY_FIRECRAWL_POSTGRES_PASSWORD"],
        "POSTGRES_DB=" + env["UNDEFINED_DEPLOY_FIRECRAWL_POSTGRES_DB"],
        "BULL_AUTH_KEY=" + env["UNDEFINED_DEPLOY_FIRECRAWL_BULL_AUTH_KEY"],
        "ALLOW_LOCAL_WEBHOOKS=true",
        "NUQ_BACKEND=postgres",
    ]
    return "\n".join(lines) + "\n"


def render_lxmusic2api_config(env: dict[str, str]) -> str:
    text = read_template("lxmusic2api.config.toml")
    return text.replace(
        LXMUSIC2API_KEY_PLACEHOLDER, env["UNDEFINED_DEPLOY_LXMUSIC2API_KEY"]
    )


# --------------------------------------------------------------------------- #
# config.toml 写入计划
# --------------------------------------------------------------------------- #


def _config_str(config: dict[str, Any], dotted_key: str) -> str | None:
    node: Any = config
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def build_patch_plan(ctx: GenerateContext, env: dict[str, str]) -> PatchPlan:
    """生成 config.toml 的最小差异写入计划。

    只写「服务拓扑」相关键；模型、提示词、访问控制等一律不碰。
    """
    urls = compose_service_urls(ctx)
    ws_url = _websocket_url(ctx)
    desired: dict[str, Any] = {
        "onebot.ws_url": ws_url,
        "onebot.token": env["UNDEFINED_DEPLOY_NAPCAT_WS_TOKEN"],
        "api.auth_key": env["UNDEFINED_DEPLOY_API_AUTH_KEY"],
        "webui.password": env["UNDEFINED_DEPLOY_WEBUI_PASSWORD"],
    }
    about: dict[str, str] = {
        "onebot.ws_url": "协议端 OneBot WebSocket 地址（依部署模式自动对齐）",
        "onebot.token": "与 NapCat 正向 WS 服务端一致的访问令牌",
        "api.auth_key": "Runtime API 鉴权密钥（自动生成）",
        "webui.password": "WebUI 登录密码（自动生成）",
    }

    # 应用实际监听的端口 = 容器内固定端口，必须与 compose 的映射目标一致。
    # 宿主端口只影响 `${BIND}:${HOST_PORT}:<容器端口>` 的左侧，可以随意覆盖。
    desired["webui.port"] = catalog.container_port("bot_webui")
    desired["api.port"] = catalog.container_port("bot_api")
    about["webui.port"] = "容器内监听端口（与 compose 映射目标一致）"
    about["api.port"] = "容器内监听端口（与 compose 映射目标一致）"

    if ctx.mode == catalog.MODE_CONTAINER:
        desired["webui.url"] = "0.0.0.0"
        desired["api.host"] = "0.0.0.0"
        desired["onebot.file_send_mode"] = "url"
        # 取 URL 去下载文件的是**协议端**（另一个容器），所以要给它一个
        # 它自己解析得到的地址：同网络内的服务名，而不是宿主网关别名。
        desired["onebot.file_send_host"] = BOT_SERVICE_NAME
        about["webui.url"] = "容器内需要监听全部地址，端口由 compose 发布"
        about["api.host"] = "容器内需要监听全部地址，端口由 compose 发布"
        about["onebot.file_send_mode"] = "协议端在另一个容器，走 Runtime 临时链接"
        about["onebot.file_send_host"] = "协议端通过 compose 服务名访问本体 Runtime"
    else:
        desired["webui.url"] = catalog.DEFAULT_PORT_BIND
        desired["api.host"] = catalog.DEFAULT_PORT_BIND
        desired["onebot.file_send_mode"] = "local"
        about["webui.url"] = "本体在宿主机，仅监听回环"
        about["api.host"] = "本体在宿主机，仅监听回环"
        about["onebot.file_send_mode"] = "本体与仓库同文件系统，可用共享路径"

    if catalog.SEARXNG.key in ctx.services:
        desired["search.searxng_url"] = urls["searxng"]
        about["search.searxng_url"] = "自托管 SearXNG 地址"
    if catalog.FIRECRAWL.key in ctx.services:
        desired["search.firecrawl_search_enabled"] = True
        desired["search.firecrawl.base_url"] = urls["firecrawl"]
        about["search.firecrawl_search_enabled"] = "启用 firecrawl_search 工具"
        about["search.firecrawl.base_url"] = "自托管 Firecrawl API 地址"
    if catalog.LXMUSIC2API.key in ctx.services:
        desired["lxmusic2api.base_url"] = urls["lxmusic2api"]
        desired["lxmusic2api.api_key"] = env["UNDEFINED_DEPLOY_LXMUSIC2API_KEY"]
        about["lxmusic2api.base_url"] = "自托管 lxmusic2api 地址"
        about["lxmusic2api.api_key"] = "与 lxmusic2api [auth].api_key 一致"

    return PatchPlan(config_path=ctx.repo / "config.toml", desired=desired, about=about)


# --------------------------------------------------------------------------- #
# 组装
# --------------------------------------------------------------------------- #


def apply_context_overrides(ctx: GenerateContext, fragments: dict[str, Any]) -> None:
    """按部署上下文微调合并后的片段（模板是静态的，这里只做必需的补充）。

    目前只有一项：container 模式启用 NagaAgent 时，把子模块目录挂进本体容器。
    ``naga_code_analysis_agent`` 的四个工具把 ``base_path`` 固定在
    ``Path.cwd()/code/NagaAgent``，而本体容器的工作目录是
    ``/data/Undefined``，不挂载的话该 Agent 在容器模式下没有可用目标
    （无参调用 ``list_directory`` 会直接在 ``iterdir()`` 上抛 FileNotFoundError）。
    """
    _mount_napcat_ws_template(ctx, fragments)

    if not (ctx.mode == catalog.MODE_CONTAINER and ctx.nagaagent):
        return
    services = fragments.get("services")
    if not isinstance(services, dict):
        return
    bot = services.get(BOT_SERVICE_NAME)
    if not isinstance(bot, dict):
        return
    volumes = bot.setdefault("volumes", [])
    if not isinstance(volumes, list):
        return
    mount = f"../{nagaagent.SUBMODULE_PATH}:{CONTAINER_REPO_PATH}/{nagaagent.SUBMODULE_PATH}:ro"
    if mount not in volumes:
        volumes.append(mount)


def _mount_napcat_ws_template(ctx: GenerateContext, fragments: dict[str, Any]) -> None:
    """把生成的 ws.json 以只读方式覆盖镜像的模板文件。

    只挂单个文件（不是整个目录），既避免遮蔽镜像里其它模板，也让入口脚本的
    ``cp /app/templates/ws.json ...`` 用的是带 token 的那份。
    """
    services = fragments.get("services")
    if not isinstance(services, dict):
        return
    napcat = services.get(NAPCAT_SERVICE_NAME)
    if not isinstance(napcat, dict):
        return
    volumes = napcat.setdefault("volumes", [])
    if not isinstance(volumes, list):
        return
    mount = f"./napcat/{NAPCAT_WS_ARTIFACT}:{NAPCAT_TEMPLATE_DIR}/ws.json:ro"
    if mount not in volumes:
        volumes.append(mount)


def build(ctx: GenerateContext) -> GeneratedConfiguration:
    """组装一次 ``up`` 的全部生成物。"""
    env = build_env(ctx)
    fragments = load_compose_fragments(compose_fragment_names(ctx))
    apply_context_overrides(ctx, fragments)
    compose_text = render_compose(fragments, project_name=catalog.COMPOSE_PROJECT_NAME)
    patch_plan = build_patch_plan(ctx, env)

    return GeneratedConfiguration(
        env=env,
        compose_text=compose_text,
        patch_plan=patch_plan,
        searxng_settings=(
            render_searxng_settings(ctx, env)
            if catalog.SEARXNG.key in ctx.services
            else None
        ),
        firecrawl_env=(
            render_firecrawl_env(env) if catalog.FIRECRAWL.key in ctx.services else None
        ),
        lxmusic2api_config=(
            render_lxmusic2api_config(env)
            if catalog.LXMUSIC2API.key in ctx.services
            else None
        ),
        napcat_ws_config=render_napcat_ws_config(ctx, env),
        napcat_ws_token=env["UNDEFINED_DEPLOY_NAPCAT_WS_TOKEN"],
        websocket_url=str(patch_plan.desired["onebot.ws_url"]),
    )


__all__ = [
    "ALLOWED_COMPOSE_TOP_KEYS",
    "BOT_SERVICE_NAME",
    "CONTAINER_REPO_PATH",
    "DOCKER_SOCKET_ENV",
    "apply_context_overrides",
    "GenerateContext",
    "GenerateError",
    "GeneratedConfiguration",
    "IMAGE_ENV_PREFIX",
    "LXMUSIC2API_KEY_PLACEHOLDER",
    "NAPCAT_SERVICE_NAME",
    "NAPCAT_TEMPLATE_DIR",
    "NAPCAT_WS_ARTIFACT",
    "NAPCAT_WS_TEMPLATE",
    "NAPCAT_WS_PORT_PLACEHOLDER",
    "NAPCAT_WS_TOKEN_PLACEHOLDER",
    "PLACEHOLDER_SECRETS",
    "SEARXNG_BASE_URL_PLACEHOLDER",
    "SEARXNG_SECRET_PLACEHOLDER",
    "TEMPLATE_PACKAGE",
    "build",
    "build_env",
    "build_patch_plan",
    "compose_fragment_names",
    "compose_service_urls",
    "load_compose_fragments",
    "random_secret",
    "read_template",
    "render_compose",
    "render_env",
    "render_firecrawl_env",
    "render_lxmusic2api_config",
    "render_napcat_ws_config",
    "render_searxng_settings",
    "reuse_or_generate",
]
