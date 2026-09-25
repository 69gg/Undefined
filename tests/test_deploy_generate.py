"""compose 与自托管服务配置生成测试（纯生成层，不碰 docker）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from Undefined.deploy import catalog, generate
from Undefined.deploy.state import DeployLayout

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
    assert f"{catalog.CONTAINER_DOCKER_SOCK}:{catalog.CONTAINER_DOCKER_SOCK}" in volumes
    assert "../config.toml:/data/Undefined/config.toml" in volumes
    assert any(volume.endswith(":/data/Undefined/data") for volume in volumes)


def test_container_mode_uses_service_names_for_internal_calls(tmp_path: Path) -> None:
    services = _compose_services(
        generate.build(_ctx(tmp_path, services=("searxng",))).compose_text
    )
    # 协议端在另一个容器里，本体要能通过别名访问宿主 Runtime
    assert (
        "host.docker.internal:host-gateway" in services["undefined-bot"]["extra_hosts"]
    )


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
    urls = generate.compose_service_urls(catalog.MODE_CONTAINER)
    assert urls["searxng"] == "http://searxng:8080"
    assert urls["firecrawl"] == "http://firecrawl-api:3002"
    assert urls["lxmusic2api"] == "http://lxmusic2api:3000"


def test_host_mode_uses_loopback_ports(tmp_path: Path) -> None:
    urls = generate.compose_service_urls(catalog.MODE_HOST)
    assert urls["searxng"] == "http://127.0.0.1:8080"
    assert urls["firecrawl"] == "http://127.0.0.1:3002"
    assert urls["lxmusic2api"] == "http://127.0.0.1:3000"


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
    assert desired["onebot.file_send_host"] == catalog.HOST_GATEWAY_ALIAS


def test_patch_plan_host_mode_topology(tmp_path: Path) -> None:
    plan = generate.build(_ctx(tmp_path, mode=catalog.MODE_HOST)).patch_plan
    desired = plan.desired
    assert desired["webui.url"] == "127.0.0.1"
    assert desired["api.host"] == "127.0.0.1"
    assert desired["onebot.file_send_mode"] == "local"


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


def test_unknown_mode_raises() -> None:
    with pytest.raises(generate.GenerateError, match="未知部署模式"):
        generate.compose_service_urls("kubernetes")
