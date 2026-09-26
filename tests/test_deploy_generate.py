"""compose 与自托管服务配置生成测试（纯生成层，不碰 docker）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from Undefined.deploy import catalog, generate, images, nagaagent
from Undefined.deploy.state import DeployLayout

REPO_ROOT = Path(__file__).resolve().parents[1]

PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _ctx(
    tmp_path: Path,
    *,
    mode: str = catalog.MODE_CONTAINER,
    services: tuple[str, ...] = (),
    nagaagent: bool = False,
    ports: dict[str, int] | None = None,
    port_bind: str = catalog.DEFAULT_PORT_BIND,
    previous_env: dict[str, str] | None = None,
    existing_config: dict[str, Any] | None = None,
) -> generate.GenerateContext:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    return generate.GenerateContext(
        repo=repo,
        layout=DeployLayout.under(repo),
        mode=mode,
        services=services,
        nagaagent=nagaagent,
        ports=ports or {},
        port_bind=port_bind,
        previous_env=previous_env or {},
        existing_config=existing_config or {},
    )


def _compose_services(text: str) -> dict[str, Any]:
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    services = data["services"]
    assert isinstance(services, dict)
    return services


def _referenced_vars(node: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(node, str):
        names.update(PLACEHOLDER_PATTERN.findall(node))
    elif isinstance(node, dict):
        for value in node.values():
            names |= _referenced_vars(value)
    elif isinstance(node, list):
        for item in node:
            names |= _referenced_vars(item)
    return names


# --------------------------------------------------------------------------- #
# 随机凭据
# --------------------------------------------------------------------------- #


def test_random_secret_length_and_charset() -> None:
    secret = generate.random_secret(32)
    assert len(secret) == 32
    assert re.fullmatch(r"[A-Za-z0-9]{32}", secret)


def test_random_secret_is_not_repeated() -> None:
    assert len({generate.random_secret(16) for _ in range(20)}) == 20


@pytest.mark.parametrize(
    "placeholder", ["", "   ", "changeme", "replace-with-your-key"]
)
def test_reuse_or_generate_replaces_placeholder(placeholder: str) -> None:
    generated = generate.reuse_or_generate(placeholder, length=24)
    assert generated != placeholder
    assert len(generated) == 24


def test_reuse_or_generate_reuses_real_value() -> None:
    assert generate.reuse_or_generate("real-secret", length=24) == "real-secret"


def test_reuse_or_generate_on_missing_value() -> None:
    assert len(generate.reuse_or_generate(None, length=12)) == 12


# --------------------------------------------------------------------------- #
# .env
# --------------------------------------------------------------------------- #


def test_env_covers_every_placeholder_used_by_templates(tmp_path: Path) -> None:
    """模板里引用的变量必须都在 .env 里——否则 compose 会报 “variable is not set”。"""
    ctx = _ctx(tmp_path, services=("searxng", "firecrawl", "lxmusic2api"))
    config = generate.build(ctx)
    referenced = _referenced_vars(yaml.safe_load(config.compose_text))
    referenced |= _referenced_vars(config.searxng_settings or "")
    assert referenced <= set(config.env), (
        f"未定义变量：{sorted(referenced - set(config.env))}"
    )


def test_host_mode_skips_bot_port_mapping_variables(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, mode=catalog.MODE_HOST)
    config = generate.build(ctx)
    # 本体不在 compose 里，就不该发布它的端口
    assert "UNDEFINED_DEPLOY_PORT_BOT_WEBUI" not in config.env
    assert "UNDEFINED_DEPLOY_PORT_BOT_WEBUI_BIND" not in config.env


def test_container_mode_publishes_bot_ports(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    env = generate.build(ctx).env
    assert env["UNDEFINED_DEPLOY_PORT_BOT_WEBUI"] == "8787"
    assert env["UNDEFINED_DEPLOY_PORT_BOT_API"] == "8788"
    assert env["UNDEFINED_DEPLOY_PORT_BOT_WEBUI_BIND"] == catalog.DEFAULT_PORT_BIND


def test_unselected_service_ports_are_not_published(tmp_path: Path) -> None:
    env = generate.build(_ctx(tmp_path)).env
    assert "UNDEFINED_DEPLOY_PORT_SEARXNG" not in env


def test_port_override_is_applied(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, ports={"napcat_ws": 13001, "bot_webui": 18787})
    env = generate.build(ctx).env
    assert env["UNDEFINED_DEPLOY_PORT_NAPCAT_WS"] == "13001"
    assert env["UNDEFINED_DEPLOY_PORT_BOT_WEBUI"] == "18787"


def test_compose_maps_host_port_to_fixed_container_port(tmp_path: Path) -> None:
    """compose 必须写成 `${BIND}:${HOST_PORT}:<容器端口>`。

    旧实现宿主与容器端口同用一个变量，用户 --port 之后应用仍监听默认端口，
    映射却指向新端口 —— WebUI 直接打不开、本体也连不上 NapCat。
    """
    ctx = _ctx(
        tmp_path,
        ports={
            "bot_webui": 19000,
            "bot_api": 19001,
            "napcat_ws": 13001,
            "napcat_webui": 16099,
            "searxng": 19090,
        },
        services=("searxng",),
    )
    services = _compose_services(generate.build(ctx).compose_text)

    def mapping_for(service: str, container_port: int) -> str:
        matches = [
            entry
            for entry in services[service]["ports"]
            if entry.endswith(f":{container_port}")
        ]
        assert len(matches) == 1, (
            f"{service} 缺少容器端口 {container_port}: {services[service]['ports']}"
        )
        return str(matches[0])

    # 宿主端口来自变量，容器端口是字面量
    assert mapping_for("undefined-bot", 8787).startswith(
        "${UNDEFINED_DEPLOY_PORT_BOT_WEBUI_BIND}:${UNDEFINED_DEPLOY_PORT_BOT_WEBUI}:"
    )
    assert mapping_for("undefined-bot", 8788).startswith(
        "${UNDEFINED_DEPLOY_PORT_BOT_API_BIND}:${UNDEFINED_DEPLOY_PORT_BOT_API}:"
    )
    assert mapping_for("napcat", 3001).startswith(
        "${UNDEFINED_DEPLOY_PORT_NAPCAT_WS_BIND}:${UNDEFINED_DEPLOY_PORT_NAPCAT_WS}:"
    )
    assert mapping_for("searxng", 8080).startswith(
        "${UNDEFINED_DEPLOY_PORT_SEARXNG_BIND}:${UNDEFINED_DEPLOY_PORT_SEARXNG}:"
    )
    # 容器侧不得再引用变量（旧写法 ${PORT}:${PORT} 会让应用与实际映射错位）
    for service in ("undefined-bot", "napcat", "searxng"):
        for entry in services[service]["ports"]:
            container = entry.rsplit(":", 1)[1]
            assert container.isdigit(), entry


def test_config_listen_ports_match_container_ports(tmp_path: Path) -> None:
    """config.toml 的监听端口必须等于 compose 的容器端口。"""
    ctx = _ctx(tmp_path, ports={"bot_webui": 19000, "bot_api": 19001})
    desired = generate.build(ctx).patch_plan.desired
    assert desired["webui.port"] == catalog.BOT_WEBUI_CONTAINER_PORT
    assert desired["api.port"] == catalog.BOT_API_CONTAINER_PORT


def test_container_ws_url_uses_container_port(tmp_path: Path) -> None:
    """容器模式连的是容器内端口；--port 覆盖只影响宿主机侧的映射。

    旧实现拼的是宿主发布端口（ws://napcat:13001），而容器网络里没有任何人在
    听那个端口——本体永远连不上协议端，status 却一切正常。
    """
    ctx = _ctx(tmp_path, ports={"napcat_ws": 13001})
    assert (
        generate.build(ctx).websocket_url
        == f"ws://{generate.NAPCAT_SERVICE_NAME}:{catalog.NAPCAT_WS_CONTAINER_PORT}"
    )


def test_host_ws_url_uses_overridden_host_port(tmp_path: Path) -> None:
    """host 模式下本体在宿主机上，走的是被覆盖后的发布端口。"""
    ctx = _ctx(tmp_path, mode=catalog.MODE_HOST, ports={"napcat_ws": 13001})
    assert generate.build(ctx).websocket_url == "ws://127.0.0.1:13001"


def test_container_service_urls_follow_catalog_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """容器模式地址里的端口必须来自 catalog，不能是写死的字面量。"""
    monkeypatch.setitem(catalog.CONTAINER_PORTS, "searxng", 18080)
    urls = generate.compose_service_urls(_ctx(tmp_path))
    assert urls["searxng"] == f"http://{generate.SEARXNG_SERVICE_NAME}:18080"


def test_port_bind_override_is_applied(tmp_path: Path) -> None:
    env = generate.build(_ctx(tmp_path, port_bind="0.0.0.0")).env
    assert env["UNDEFINED_DEPLOY_PORT_NAPCAT_WEBUI_BIND"] == "0.0.0.0"


def test_credentials_are_reused_across_runs(tmp_path: Path) -> None:
    """幂等性核心：重跑 up 不能把已经生效的 token/密码换掉。"""
    first = generate.build(_ctx(tmp_path)).env
    second = generate.build(_ctx(tmp_path, previous_env=dict(first))).env
    for key in (
        "UNDEFINED_DEPLOY_NAPCAT_WEBUI_TOKEN",
        "UNDEFINED_DEPLOY_NAPCAT_WS_TOKEN",
        "UNDEFINED_DEPLOY_WEBUI_PASSWORD",
        "UNDEFINED_DEPLOY_API_AUTH_KEY",
        "UNDEFINED_DEPLOY_SEARXNG_SECRET",
        "UNDEFINED_DEPLOY_LXMUSIC2API_KEY",
    ):
        assert first[key] == second[key], f"{key} 在重跑时被重新生成"


def test_existing_config_credentials_are_reused(tmp_path: Path) -> None:
    """config.toml 里已有可用凭据时不要改动用户环境。"""
    ctx = _ctx(
        tmp_path,
        existing_config={
            "webui": {"password": "user-password"},
            "api": {"auth_key": "user-api-key"},
        },
    )
    env = generate.build(ctx).env
    assert env["UNDEFINED_DEPLOY_WEBUI_PASSWORD"] == "user-password"
    assert env["UNDEFINED_DEPLOY_API_AUTH_KEY"] == "user-api-key"


def test_default_credentials_are_regenerated(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        existing_config={"webui": {"password": "changeme"}, "api": {"auth_key": ""}},
    )
    env = generate.build(ctx).env
    assert env["UNDEFINED_DEPLOY_WEBUI_PASSWORD"] != "changeme"
    assert env["UNDEFINED_DEPLOY_API_AUTH_KEY"]


@pytest.mark.parametrize("placeholder", sorted(generate.PLACEHOLDER_SECRETS - {""}))
def test_config_credentials_win_over_placeholder_env(
    tmp_path: Path, placeholder: str
) -> None:
    """``.env`` 里的占位值不得挡掉 config.toml 里真正生效的密码。

    ``prev(...) or _config_str(...)`` 只判真假，而 ``changeme`` 这类占位值是**真值**：
    它会顶掉第二个来源，然后被 ``reuse_or_generate`` 丢掉换成随机值——重跑一次 up
    就把用户正在用的 WebUI 密码与 Runtime API key 无声换掉了。
    """
    ctx = _ctx(
        tmp_path,
        previous_env={
            "UNDEFINED_DEPLOY_WEBUI_PASSWORD": placeholder,
            "UNDEFINED_DEPLOY_API_AUTH_KEY": placeholder,
        },
        existing_config={
            "webui": {"password": "user-password"},
            "api": {"auth_key": "user-api-key"},
        },
    )
    env = generate.build(ctx).env
    assert env["UNDEFINED_DEPLOY_WEBUI_PASSWORD"] == "user-password"
    assert env["UNDEFINED_DEPLOY_API_AUTH_KEY"] == "user-api-key"


def test_config_credentials_win_over_stale_env(tmp_path: Path) -> None:
    """两个来源都可用时以 config.toml 为准。

    这两个键只在 config.toml 里生效（``.env`` 只是留档供下次复用），所以重跑 up
    应当向「实际生效的值」收敛，而不是把手改过的密码改回旧的 .env 值。
    """
    ctx = _ctx(
        tmp_path,
        previous_env={
            "UNDEFINED_DEPLOY_WEBUI_PASSWORD": "stale-env-password",
            "UNDEFINED_DEPLOY_API_AUTH_KEY": "stale-env-key",
        },
        existing_config={
            "webui": {"password": "current-password"},
            "api": {"auth_key": "current-key"},
        },
    )
    env = generate.build(ctx).env
    assert env["UNDEFINED_DEPLOY_WEBUI_PASSWORD"] == "current-password"
    assert env["UNDEFINED_DEPLOY_API_AUTH_KEY"] == "current-key"


def test_render_env_is_sorted_and_commented(tmp_path: Path) -> None:
    env = generate.build(_ctx(tmp_path)).env
    text = generate.render_env(env)
    assert text.startswith("#")
    keys = [
        line.split("=", 1)[0]
        for line in text.splitlines()
        if line and not line.startswith("#")
    ]
    assert keys == sorted(keys)
    assert "UNDEFINED_DEPLOY_BOT_IMAGE" in keys


# --------------------------------------------------------------------------- #
# compose 渲染
# --------------------------------------------------------------------------- #


def test_container_mode_includes_bot_and_napcat(tmp_path: Path) -> None:
    services = _compose_services(generate.build(_ctx(tmp_path)).compose_text)
    assert set(services) == {"undefined-bot", "napcat"}


def test_host_mode_excludes_bot(tmp_path: Path) -> None:
    services = _compose_services(
        generate.build(_ctx(tmp_path, mode=catalog.MODE_HOST)).compose_text
    )
    assert set(services) == {"napcat"}


@pytest.mark.parametrize(
    ("service", "expected"),
    [
        ("searxng", "searxng"),
        ("firecrawl", "firecrawl-api"),
        ("lxmusic2api", "lxmusic2api"),
    ],
)
def test_selected_service_is_added(tmp_path: Path, service: str, expected: str) -> None:
    services = _compose_services(
        generate.build(_ctx(tmp_path, services=(service,))).compose_text
    )
    assert expected in services


def test_lxmusic2api_runs_as_invoking_user(tmp_path: Path) -> None:
    """上游镜像以 USER node(1000) 运行，而挂载目录按调用者 uid 创建。

    uid 不一致时它连启动都会失败并进入 restart 崩溃循环（审查 M7），
    因此 compose 必须显式指定 user 为调用者 uid:gid。
    """
    services = _compose_services(
        generate.build(_ctx(tmp_path, services=("lxmusic2api",))).compose_text
    )
    user = str(services["lxmusic2api"].get("user") or "")
    assert user, "缺少 user 指令，非 1000 用户部署会崩溃循环"
    assert user == (
        "${UNDEFINED_DEPLOY_LXMUSIC2API_UID}:${UNDEFINED_DEPLOY_LXMUSIC2API_GID}"
    ), user


def test_firecrawl_brings_its_whole_stack(tmp_path: Path) -> None:
    services = _compose_services(
        generate.build(_ctx(tmp_path, services=("firecrawl",))).compose_text
    )
    assert {
        "firecrawl-api",
        "firecrawl-playwright",
        "firecrawl-redis",
        "firecrawl-rabbitmq",
        "firecrawl-postgres",
    } <= set(services)


def test_lxmusic2api_image_is_only_resolved_when_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未选 lxmusic2api 时不得解析它的镜像 tag。

    ``short_sha`` 对占位 pin 直接抛 ValueError；无条件解析会让**任何**一次
    ``uv run deploy`` 失败，哪怕根本没选这个服务（CI 侧特意做成「跳过而不失败」，
    两边语义必须一致）。
    """
    monkeypatch.setattr(images, "LXMUSIC2API_UPSTREAM_SHA", "PLACEHOLDER")

    env = generate.build(_ctx(tmp_path)).env
    assert f"{generate.IMAGE_ENV_PREFIX}LXMUSIC2API_IMAGE" not in env

    with pytest.raises(ValueError):
        generate.build(_ctx(tmp_path, services=("lxmusic2api",)))


def test_napcat_webui_preferred_port_stays_a_container_port(tmp_path: Path) -> None:
    """NAPCAT_WEBUI_PREFERRED_PORT 会被 core 当作**容器内**监听端口。

    早先传的是宿主端口变量：默认值恰好也是 6099 所以看不出问题，一旦
    --port napcat_webui=16099，容器内就改绑 16099，而映射仍是 16099:6099，
    WebUI 彻底打不开。
    """
    services = _compose_services(
        generate.build(_ctx(tmp_path, ports={"napcat_webui": 16099})).compose_text
    )
    napcat = services["napcat"]
    preferred = str(napcat["environment"].get("NAPCAT_WEBUI_PREFERRED_PORT", ""))
    assert preferred == str(catalog.NAPCAT_WEBUI_CONTAINER_PORT), (
        f"NAPCAT_WEBUI_PREFERRED_PORT 必须是容器内端口 "
        f"{catalog.NAPCAT_WEBUI_CONTAINER_PORT}，当前是 {preferred!r}"
    )

    webui_mapping = [entry for entry in napcat["ports"] if entry.endswith(":6099")]
    assert webui_mapping, f"WebUI 端口映射的目标端必须是 6099：{napcat['ports']}"


def test_searxng_does_not_chown_the_mounted_config_dir(tmp_path: Path) -> None:
    """入口的 chown 会把宿主 deploy/searxng 改成 977:977，之后再也写不进去。

    下一次 up 要重写 settings.yml，于是直接 EACCES——部署脚本「幂等、重跑即可改
    选择」的承诺就破了。容器以 root 运行、settings.yml 是脚本原子写入的 0600，
    不需要 chown。
    """
    services = _compose_services(
        generate.build(_ctx(tmp_path, services=("searxng",))).compose_text
    )
    environment = services["searxng"]["environment"]
    ownership = environment.get("FORCE_OWNERSHIP")
    assert str(ownership).lower() == "false", (
        "searxng 必须显式关闭 FORCE_OWNERSHIP，否则入口会 chown 掉 bind mount 的"
        f"宿主目录（当前值：{ownership!r}）"
    )


def test_compose_declares_project_name_and_network(tmp_path: Path) -> None:
    data = yaml.safe_load(generate.build(_ctx(tmp_path)).compose_text)
    assert data["name"] == catalog.COMPOSE_PROJECT_NAME
    assert "undefined-deploy" in data["networks"]


def test_compose_has_no_variable_defaults(tmp_path: Path) -> None:
    """模板不写 ``${VAR:-default}``：变量名拼错要直接报错而不是静默取默认值。"""
    text = generate.build(_ctx(tmp_path, services=("firecrawl",))).compose_text
    assert ":-" not in text


def test_bot_container_mounts_repo_and_docker_socket(tmp_path: Path) -> None:
    services = _compose_services(generate.build(_ctx(tmp_path)).compose_text)
    bot = services["undefined-bot"]
    volumes = bot["volumes"]
    # socket 路径走变量，容器内固定挂在同一路径（DooD）
    assert "${UNDEFINED_DEPLOY_DOCKER_SOCKET}:/var/run/docker.sock" in volumes
    # 必须是**目录**挂载（且可写）：`up` 用 os.replace 原子替换 config.toml，单文件
    # bind mount 绑的是替换前的 inode，容器会一直读旧配置；而挂成 :ro 会让 WebUI 的
    # 配置保存（CONFIG_PATH.write_text，原地写）直接失败。
    assert "..:/data/Undefined" in volumes, volumes
    assert not [v for v in volumes if v.startswith("../config.toml:")], volumes
    # 静态资源仍只读；运行态 data/logs 走 deploy/ 下的目录
    assert "../res:/data/Undefined/res:ro" in volumes, volumes
    assert any(volume.endswith(":/data/Undefined/data") for volume in volumes)


def test_container_mode_points_file_send_host_at_the_bot_service(
    tmp_path: Path,
) -> None:
    """协议端要按**自己**能解析的地址去下载文件。

    取 URL 去取文件的是 NapCat（另一个容器），所以 file_send_host 必须是同网络
    的服务名；写成 host.docker.internal 会加到错误一侧（别名在本体容器上无效），
    而且 Runtime API 默认只绑回环，协议端经宿主网关也连不上。
    """
    config = generate.build(_ctx(tmp_path, services=("searxng",)))
    assert (
        config.patch_plan.desired["onebot.file_send_host"] == generate.BOT_SERVICE_NAME
    )

    services = _compose_services(config.compose_text)
    # 本体容器不需要宿主网关别名
    assert "extra_hosts" not in services["undefined-bot"]


def test_container_mode_mounts_nagaagent_submodule_when_enabled(
    tmp_path: Path,
) -> None:
    """启用 NagaAgent 时必须把子模块挂进本体容器。

    ``naga_code_analysis_agent`` 的工具把 base_path 固定在
    ``Path.cwd()/code/NagaAgent``；本体容器的工作目录是 /data/Undefined，
    不挂载的话该 Agent 在容器模式下没有可用目标（曾只写在文档里而没实现）。
    """
    services = _compose_services(
        generate.build(_ctx(tmp_path, nagaagent=True)).compose_text
    )
    volumes = services["undefined-bot"]["volumes"]
    assert "../code/NagaAgent:/data/Undefined/code/NagaAgent:ro" in volumes, (
        f"缺少 NagaAgent 只读挂载：{volumes}"
    )


def test_nagaagent_mount_absent_when_disabled(tmp_path: Path) -> None:
    services = _compose_services(generate.build(_ctx(tmp_path)).compose_text)
    volumes = services["undefined-bot"]["volumes"]
    assert not [v for v in volumes if "NagaAgent" in v]


def test_nagaagent_mount_absent_in_host_mode(tmp_path: Path) -> None:
    """host 模式本体不在容器里，无需挂载。"""
    services = _compose_services(
        generate.build(
            _ctx(tmp_path, mode=catalog.MODE_HOST, nagaagent=True)
        ).compose_text
    )
    assert "undefined-bot" not in services


def test_duplicate_service_definitions_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(generate.GenerateError, match="重复定义"):
        generate.load_compose_fragments(["compose.napcat.yaml", "compose.napcat.yaml"])


def test_unknown_top_level_key_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        generate, "read_template", lambda name: "name: nope\nservices: {}\n"
    )
    with pytest.raises(generate.GenerateError, match="不支持的顶层键"):
        generate.load_compose_fragments(["compose.base.yaml"])


def test_missing_template_raises() -> None:
    with pytest.raises(generate.GenerateError):
        generate.read_template("compose.nope.yaml")


def test_non_mapping_template_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generate, "read_template", lambda name: "- just\n- a list\n")
    with pytest.raises(generate.GenerateError, match="顶层必须是映射"):
        generate.load_compose_fragments(["compose.base.yaml"])


# --------------------------------------------------------------------------- #
# 各服务配置
# --------------------------------------------------------------------------- #


def test_searxng_settings_enable_json_and_disable_limiter(tmp_path: Path) -> None:
    """不开 json 格式时 SearXNG 对 format=json 直接返回 403，web_search 会全挂。"""
    config = generate.build(_ctx(tmp_path, services=("searxng",)))
    assert config.searxng_settings is not None
    parsed = yaml.safe_load(config.searxng_settings)
    assert parsed["use_default_settings"] is True
    assert parsed["search"]["formats"] == ["html", "json"]
    assert parsed["server"]["limiter"] is False
    assert (
        parsed["server"]["secret_key"] == config.env["UNDEFINED_DEPLOY_SEARXNG_SECRET"]
    )
    # 占位标记必须被替换干净
    assert "__UNDEFINED_DEPLOY" not in config.searxng_settings


def test_searxng_settings_absent_when_not_selected(tmp_path: Path) -> None:
    assert generate.build(_ctx(tmp_path)).searxng_settings is None


def test_firecrawl_env_leaves_nuq_backend_unset(tmp_path: Path) -> None:
    """NUQ_BACKEND 必须留空。

    上游 `apps/api/src/config.ts` 把它声明成 `z.enum(["pg", "fdb"]).optional()`
    并在启动时 `parse(process.env)`；写 `postgres` 会抛 Zod 错误，api 容器永远
    起不来且日志里只有一句 zod 报错。不写即取默认的 pg 后端。
    """
    config = generate.build(_ctx(tmp_path, services=("firecrawl",)))
    assert config.firecrawl_env is not None
    assert not [
        line
        for line in config.firecrawl_env.splitlines()
        if line.startswith("NUQ_BACKEND")
    ]


def _internal_hostname(value: str) -> str | None:
    """取出需要容器内 DNS 解析的主机名；外部地址与绑定地址返回 None。"""
    text = value.strip()
    match = re.match(r"^[a-z][a-z0-9+.-]*://([^/:]+)", text)
    host = match.group(1) if match else text.split("/", 1)[0]
    if not host or host in {"localhost", "0.0.0.0", "127.0.0.1"}:
        return None
    if "." in host:  # IP 或外部 FQDN，不需要在 compose 网络里解析
        return None
    return host


def test_compose_internal_hosts_point_at_declared_services(tmp_path: Path) -> None:
    """compose 里引用的主机名必须是同一份文件声明过的服务或容器名。

    上游 compose 用的是 redis / rabbitmq / postgres 这类默认名，我们统一加了
    ``firecrawl-`` 前缀；漏改一处就会出现「容器 running、但 worker 连不上
    broker」这种既没有报错也没有日志的静默故障（NUQ_RABBITMQ_URL 就漏过一次）。
    """
    data = yaml.safe_load(
        generate.build(_ctx(tmp_path, services=("firecrawl",))).compose_text
    )
    services: dict[str, Any] = data["services"]
    declared = set(services) | {
        spec["container_name"]
        for spec in services.values()
        if isinstance(spec.get("container_name"), str)
    }

    checked: list[str] = []
    for name, spec in services.items():
        for key, value in (spec.get("environment") or {}).items():
            if not key.endswith(("_URL", "_HOST", "_ENDPOINT")):
                continue
            host = _internal_hostname(str(value))
            if host is None:
                continue
            checked.append(f"{name}.{key}={host}")
            assert host in declared, (
                f"{name} 的 {key} 指向 {host!r}，但同一份 compose 里没有这个"
                f"服务/容器名；已声明：{sorted(declared)}"
            )
    # 防止断言退化：一个内部主机名都没解析到时必须报错，而不是静默通过
    assert checked, "没有解析到任何内部主机名，该断言已形同虚设"


def test_firecrawl_env_disables_db_auth(tmp_path: Path) -> None:
    config = generate.build(_ctx(tmp_path, services=("firecrawl",)))
    assert config.firecrawl_env is not None
    env = dict(
        line.split("=", 1)
        for line in config.firecrawl_env.splitlines()
        if line and not line.startswith("#")
    )
    # 自托管场景必须关掉 DB 鉴权，否则 api 容器起不来
    assert env["USE_DB_AUTHENTICATION"] == "false"
    assert (
        env["POSTGRES_PASSWORD"]
        == (config.env["UNDEFINED_DEPLOY_FIRECRAWL_POSTGRES_PASSWORD"])
    )
    assert (
        env["BULL_AUTH_KEY"] == config.env["UNDEFINED_DEPLOY_FIRECRAWL_BULL_AUTH_KEY"]
    )


def test_lxmusic2api_config_has_mandatory_fields(tmp_path: Path) -> None:
    """这三项任一不满足上游会拒绝启动。"""
    config = generate.build(_ctx(tmp_path, services=("lxmusic2api",)))
    assert config.lxmusic2api_config is not None
    import tomllib

    parsed = tomllib.loads(config.lxmusic2api_config)
    assert parsed["legal"]["accept_lx_music_terms"] is True
    assert parsed["server"]["host"] == "0.0.0.0"
    assert len(parsed["auth"]["api_key"]) >= 32
    assert parsed["auth"]["api_key"] == config.env["UNDEFINED_DEPLOY_LXMUSIC2API_KEY"]


# --------------------------------------------------------------------------- #
# base_url 与 config.toml 写入计划
# --------------------------------------------------------------------------- #


def test_container_mode_uses_compose_service_names(tmp_path: Path) -> None:
    urls = generate.compose_service_urls(_ctx(tmp_path))
    assert urls["searxng"] == "http://searxng:8080"
    assert urls["firecrawl"] == "http://firecrawl-api:3002"
    assert urls["lxmusic2api"] == "http://lxmusic2api:3000"


def test_host_mode_uses_loopback_ports(tmp_path: Path) -> None:
    urls = generate.compose_service_urls(_ctx(tmp_path, mode=catalog.MODE_HOST))
    assert urls["searxng"] == "http://127.0.0.1:8080"
    assert urls["firecrawl"] == "http://127.0.0.1:3002"
    assert urls["lxmusic2api"] == "http://127.0.0.1:3000"


def test_host_mode_urls_honour_port_overrides(tmp_path: Path) -> None:
    """host 模式只能走发布端口，必须用覆盖后的值。

    旧实现取的是 specs[...].default，用户 --port 之后写回 config.toml 的地址永远
    是默认端口，服务全连不上且没有任何报错。
    """
    ctx = _ctx(
        tmp_path,
        mode=catalog.MODE_HOST,
        ports={"searxng": 19090, "firecrawl": 13002, "lxmusic2api": 13000},
        port_bind="192.168.1.5",
    )
    urls = generate.compose_service_urls(ctx)
    assert urls["searxng"] == "http://192.168.1.5:19090"
    assert urls["firecrawl"] == "http://192.168.1.5:13002"
    assert urls["lxmusic2api"] == "http://192.168.1.5:13000"


def test_websocket_url_per_mode(tmp_path: Path) -> None:
    container = generate.build(_ctx(tmp_path))
    host = generate.build(_ctx(tmp_path, mode=catalog.MODE_HOST))
    assert container.websocket_url == "ws://napcat:3001"
    assert host.websocket_url == "ws://127.0.0.1:3001"


def test_patch_plan_container_mode_topology(tmp_path: Path) -> None:
    plan = generate.build(_ctx(tmp_path)).patch_plan
    desired = plan.desired
    assert desired["webui.url"] == "0.0.0.0"
    assert desired["api.host"] == "0.0.0.0"
    # 协议端在另一个容器里，本地路径模式不可用
    assert desired["onebot.file_send_mode"] == "url"
    assert desired["onebot.file_send_host"] == generate.BOT_SERVICE_NAME
    # 镜像入口是 WebUI，容器里没人手点「启动机器人」：不自动拉起就等于没部署
    assert desired["webui.autostart_bot"] is True


def test_patch_plan_host_mode_topology(tmp_path: Path) -> None:
    plan = generate.build(_ctx(tmp_path, mode=catalog.MODE_HOST)).patch_plan
    desired = plan.desired
    assert desired["webui.url"] == "127.0.0.1"
    assert desired["api.host"] == "127.0.0.1"
    assert desired["onebot.file_send_mode"] == "local"
    # 宿主机上由用户自己决定怎么起 Bot，部署脚本不该改写这个偏好
    assert "webui.autostart_bot" not in desired


def test_patch_plan_only_touches_selected_services(tmp_path: Path) -> None:
    plan = generate.build(_ctx(tmp_path)).patch_plan
    assert "search.searxng_url" not in plan.desired
    assert "search.firecrawl_search_enabled" not in plan.desired
    assert "lxmusic2api.base_url" not in plan.desired


def test_patch_plan_aligns_selected_service_urls(tmp_path: Path) -> None:
    plan = generate.build(
        _ctx(tmp_path, services=("searxng", "firecrawl", "lxmusic2api"))
    ).patch_plan
    assert plan.desired["search.searxng_url"] == "http://searxng:8080"
    assert plan.desired["search.firecrawl_search_enabled"] is True
    assert plan.desired["search.firecrawl.base_url"] == "http://firecrawl-api:3002"
    assert plan.desired["lxmusic2api.base_url"] == "http://lxmusic2api:3000"


def test_patch_plan_never_touches_model_config(tmp_path: Path) -> None:
    """模型端配置必须留给用户，部署脚本不得代填。"""
    plan = generate.build(_ctx(tmp_path)).patch_plan
    assert not [key for key in plan.desired if key.startswith("models")]


def test_host_mode_bot_ports_follow_the_port_override(tmp_path: Path) -> None:
    """host 模式没有映射层：本体自己监听，端口必须跟随 --port。

    旧实现无论哪种模式都写容器内端口，于是 host 模式下
    `--port bot_webui=9000` 被静默忽略，还会把手改过的 [webui].port 改回 8787。
    """
    ctx = _ctx(
        tmp_path, mode=catalog.MODE_HOST, ports={"bot_webui": 9000, "bot_api": 9001}
    )
    desired = generate.build(ctx).patch_plan.desired
    assert desired["webui.port"] == 9000
    assert desired["api.port"] == 9001


def test_host_mode_bot_ports_default_without_override(tmp_path: Path) -> None:
    desired = generate.build(_ctx(tmp_path, mode=catalog.MODE_HOST)).patch_plan.desired
    assert desired["webui.port"] == catalog.BOT_WEBUI_CONTAINER_PORT
    assert desired["api.port"] == catalog.BOT_API_CONTAINER_PORT


def test_every_written_key_exists_in_the_config_template(tmp_path: Path) -> None:
    """部署脚本写进 config.toml 的每个键都必须真实存在于配置模板。

    拼错一个键不会报错——`apply_patch` 会兴高采烈地写进去，而配置加载器读的是
    另一个键，表现为「脚本说写好了，功能就是不生效」。这条断言把写入面钉在
    `config.toml.example`（配置模型的真实形状）上。
    """
    import tomllib

    example = (REPO_ROOT / "config.toml.example").read_text(encoding="utf-8")
    model = tomllib.loads(example)

    plan = generate.build(
        _ctx(tmp_path, services=("searxng", "firecrawl", "lxmusic2api"))
    ).patch_plan
    assert plan.desired, "patch plan 是空的，这条断言会形同虚设"

    for dotted in plan.desired:
        node: Any = model
        for part in dotted.split("."):
            assert isinstance(node, dict) and part in node, (
                f"{dotted} 在 config.toml.example 里不存在；（走到 {part!r} 时断了）"
            )
            node = node[part]


def test_naga_only_writes_the_feature_switch(tmp_path: Path) -> None:
    """NagaAgent 相关写入同样必须落在真实配置键上（且只有总闸）。"""
    import tomllib

    model = tomllib.loads(
        (REPO_ROOT / "config.toml.example").read_text(encoding="utf-8")
    )
    for enabled in (True, False):
        plan = nagaagent.build_patch_plan(tmp_path, nagaagent=enabled)
        assert list(plan.desired) == ["features.nagaagent_mode_enabled"]
        assert "nagaagent_mode_enabled" in model["features"]


def test_patch_plan_config_path_is_repo_root(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    assert generate.build(ctx).patch_plan.config_path == ctx.repo / "config.toml"


def test_napcat_ws_token_is_shared_with_config(tmp_path: Path) -> None:
    """config.toml 的 [onebot].token 必须与写进 NapCat 的 WS token 一致。"""
    config = generate.build(_ctx(tmp_path))
    assert config.patch_plan.desired["onebot.token"] == config.napcat_ws_token


def test_unknown_port_key_raises(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    with pytest.raises(generate.GenerateError, match="未知端口键"):
        ctx.port("nope")


def test_unknown_mode_raises(tmp_path: Path) -> None:
    with pytest.raises(generate.GenerateError, match="未知部署模式"):
        generate.compose_service_urls(_ctx(tmp_path, mode="kubernetes"))


def test_host_mode_connect_urls_never_use_wildcard_bind(tmp_path: Path) -> None:
    """0.0.0.0 是监听语义，不能当成连接目标写进配置。

    旧实现直接把 --port-bind 拼进 URL，于是 `--port-bind 0.0.0.0` 会生成
    `http://0.0.0.0:8080`；而同一份代码里的 SearXNG base_url 却做了
    0.0.0.0→localhost 的映射，前后不一致。
    """
    ctx = _ctx(
        tmp_path,
        mode=catalog.MODE_HOST,
        port_bind="0.0.0.0",
        services=("searxng", "firecrawl", "lxmusic2api"),
    )
    config = generate.build(ctx)

    for url in generate.compose_service_urls(ctx).values():
        assert "0.0.0.0" not in url, url
    assert "0.0.0.0" not in config.websocket_url
    assert "0.0.0.0" not in config.env["UNDEFINED_DEPLOY_SEARXNG_BASE_URL"]


def test_bot_container_forbids_privilege_escalation(tmp_path: Path) -> None:
    """本体容器以 root 运行且挂着宿主 docker.sock，至少要禁止提权。

    这条不会影响容器内的 Playwright：Chromium 只在显式传 chromiumSandbox: true
    时才启用自带沙箱，否则 Playwright 会自己加 --no-sandbox。
    """
    services = _compose_services(generate.build(_ctx(tmp_path)).compose_text)
    security_opt = services["undefined-bot"].get("security_opt") or []
    assert "no-new-privileges:true" in security_opt, security_opt
