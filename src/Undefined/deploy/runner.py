"""``up`` / ``down`` / ``status`` / ``logs`` 的具体流程。

串起「交互确认 → 生成 → 写盘 → 调 docker → 输出入口与凭据」。
所有子命令都幂等：重复执行不换凭据、不覆盖用户手工修改。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Sequence

from Undefined.deploy import (
    catalog,
    config_patch,
    docker_cli,
    generate,
    images,
    nagaagent,
)
from Undefined.deploy.catalog import EXIT_ERROR, EXIT_OK
from Undefined.deploy.docker_cli import DryRunRunner, Runner
from Undefined.deploy.state import (
    DeployLayout,
    DeployState,
    read_state,
    repo_root,
    save_state,
    write_text,
)

#: NapCat 由镜像入口按 MODE=ws 生成的 OneBot 配置文件名。
NAPCAT_ONEBOT_CONFIG = "onebot11.json"

#: NapCat 容器名（与模板一致），用于 ``status`` 提示扫码。
NAPCAT_CONTAINER = "napcat"


# --------------------------------------------------------------------------- #
# .env 读写
# --------------------------------------------------------------------------- #


def parse_env_text(text: str) -> dict[str, str]:
    """解析 ``KEY=value`` 形式；忽略注释与空行。"""
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            result[key] = value.strip()
    return result


def load_previous_env(layout: DeployLayout) -> dict[str, str]:
    """读取上次生成的 ``.env``（不存在或损坏时返回空字典）。"""
    if not layout.env_file.is_file():
        return {}
    try:
        return parse_env_text(layout.env_file.read_text(encoding="utf-8"))
    except OSError:
        return {}


# --------------------------------------------------------------------------- #
# 交互
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Wizard:
    """极简交互向导：只用标准库，非 TTY 或 ``--yes`` 时跳过。"""

    enabled: bool = True

    def choose_mode(self, default: str) -> str:
        if not self.enabled:
            return default
        labels = {
            catalog.MODE_CONTAINER: "本体也跑在 Docker 里（推荐：一条命令跑完全部）",
            catalog.MODE_HOST: "本体跑在宿主机（只用 Docker 跑依赖服务）",
        }
        options = [catalog.MODE_CONTAINER, catalog.MODE_HOST]
        default_index = options.index(default) + 1 if default in options else 1
        index = self._choose(
            "本体部署方式", [labels[item] for item in options], default_index
        )
        return options[index]

    def choose_services(self, default: Sequence[str]) -> tuple[str, ...]:
        if not self.enabled:
            return tuple(default)
        items = list(catalog.OPTIONAL_SERVICES)
        print("\n额外部署哪些自托管服务？（可多选，回车=全不部署）")
        for position, service in enumerate(items, start=1):
            print(f"  {position}) {service.label} — {service.about}")
        raw = self._ask("请输入编号，逗号或空格分隔")
        if not raw.strip():
            return tuple(default)
        chosen: list[str] = []
        for token in raw.replace(",", " ").split():
            if not token.isdigit():
                print(f"  忽略无法识别的输入：{token}")
                continue
            position = int(token)
            if not 1 <= position <= len(items):
                print(f"  忽略超出范围的编号：{position}")
                continue
            key = items[position - 1].key
            if key not in chosen:
                chosen.append(key)
        return tuple(chosen)

    def choose_nagaagent(self, default: bool) -> bool:
        if not self.enabled:
            return default
        print(
            "\n是否拉取 NagaAgent 子模块？\n"
            "  是：开启 NagaAgent 代码问答能力（外部网关仍保持关闭，不连服务器）\n"
            "  否：关闭全部 Naga 相关配置（默认）"
        )
        return self._ask_yes_no("拉取 NagaAgent 子模块吗？", default)

    def choose_port_bind(self, default: str) -> str:
        if not self.enabled:
            return default
        print(
            f"\n服务端口绑定地址（默认 {default}，仅本机可访问）。\n"
            "  若需要远程访问 WebUI，可填 0.0.0.0，但请自行确保网络与鉴权安全。"
        )
        raw = self._ask(f"绑定地址 [{default}]")
        return raw.strip() or default

    def confirm(self, question: str, default: bool = True) -> bool:
        if not self.enabled:
            return default
        return self._ask_yes_no(question, default)

    # -- 底层输入 ---------------------------------------------------------- #

    def _ask(self, prompt: str) -> str:
        try:
            return input(f"{prompt}: ")
        except (EOFError, KeyboardInterrupt):
            print("\n（未输入，使用默认值）")
            return ""

    def _ask_yes_no(self, prompt: str, default: bool) -> bool:
        hint = "Y/n" if default else "y/N"
        raw = self._ask(f"{prompt} [{hint}]").strip().lower()
        if not raw:
            return default
        return raw in ("y", "yes", "是", "1", "true")

    def _choose(self, title: str, options: Sequence[str], default_index: int) -> int:
        print(f"\n{title}：")
        for position, text in enumerate(options, start=1):
            marker = "（默认）" if position == default_index else ""
            print(f"  {position}) {text}{marker}")
        raw = self._ask(f"请输入编号 [{default_index}]").strip()
        if not raw:
            return default_index - 1
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print(f"  输入无效，使用默认项 {default_index}")
        return default_index - 1


def wizard_enabled(args: dict[str, Any]) -> bool:
    """只有交互式终端且未指定 ``--yes`` 时才进入向导。"""
    if args.get("yes"):
        return False
    if args.get("command") != "up":
        return False
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, ValueError):  # pragma: no cover - 取决于运行环境
        return False


# --------------------------------------------------------------------------- #
# 展示
# --------------------------------------------------------------------------- #


def describe_patch_plan(plan: config_patch.PatchPlan, current: dict[str, Any]) -> None:
    """打印将写入的 config.toml 差异。"""
    items = plan.items(current)
    changes = [item for item in items if item.is_change]
    if not changes:
        print("config.toml：无需变更")
        return
    print("config.toml 将写入：")
    for item in changes:
        note = f"  # {item.about}" if item.about else ""
        print(f"  - {item.describe()}{note}")
    conflicts = [item for item in changes if item.is_conflict]
    if conflicts:
        print(
            "  提示：以下键已有取值，将按上方计划覆盖；原文件会自动备份到 deploy/backup/："
        )
        for item in conflicts:
            print(f"      {item.key}")


def print_access_summary(
    layout: DeployLayout,
    env: dict[str, str],
    *,
    mode: str,
    services: Sequence[str],
    nagaagent_enabled: bool,
) -> None:
    """打印各服务入口与凭据——这是 ``up`` 最有价值的输出。"""
    specs = catalog.port_specs()

    def port(key: str) -> int:
        raw = env.get(specs[key].env_var)
        return int(raw) if raw and raw.isdigit() else specs[key].default

    bind = env.get(specs["bot_webui"].bind_env_var, catalog.DEFAULT_PORT_BIND)
    host = "127.0.0.1" if bind in ("0.0.0.0", "::") else bind

    print("\n" + "=" * 68)
    print("部署完成，服务入口：")
    print("=" * 68)

    if mode == catalog.MODE_CONTAINER:
        print(f"  Undefined WebUI   http://{host}:{port('bot_webui')}")
        print(f"    密码            {env.get('UNDEFINED_DEPLOY_WEBUI_PASSWORD', '')}")
        print(f"  Runtime API       http://{host}:{port('bot_api')}")
        print(f"    auth_key        {env.get('UNDEFINED_DEPLOY_API_AUTH_KEY', '')}")
    else:
        print("  本体跑在宿主机，请另开终端执行： uv run Undefined-webui")
        print(f"  Undefined WebUI   http://{host}:{port('bot_webui')}")
        print(f"    密码            {env.get('UNDEFINED_DEPLOY_WEBUI_PASSWORD', '')}")

    napcat_token = env.get("UNDEFINED_DEPLOY_NAPCAT_WEBUI_TOKEN", "")
    print(
        f"  NapCat WebUI      http://{host}:{port('napcat_webui')}/webui?token={napcat_token}"
    )
    print(f"  NapCat 协议端     ws://127.0.0.1:{port('napcat_ws')}（供本体连接）")

    if catalog.SEARXNG.key in services:
        print(f"  SearXNG           http://{host}:{port('searxng')}/")
    if catalog.FIRECRAWL.key in services:
        bull = env.get("UNDEFINED_DEPLOY_FIRECRAWL_BULL_AUTH_KEY", "")
        print(f"  Firecrawl API     http://{host}:{port('firecrawl')}")
        print(
            f"    队列管理页      http://{host}:{port('firecrawl')}/admin/{bull}/queues"
        )
        print("    说明            自托管 Firecrawl 无 dashboard，仅上面这个队列页")
    if catalog.LXMUSIC2API.key in services:
        print(
            f"  lxmusic2api       http://{host}:{port('lxmusic2api')}/docs（只读接口文档）"
        )
        print(f"    api_key         {env.get('UNDEFINED_DEPLOY_LXMUSIC2API_KEY', '')}")
        source_dir = layout.lxmusic2api_private_dir
        if not any(source_dir.glob("*.js")):
            print("    ⚠ 未检测到自定义音源脚本：搜索/歌单可用，取音频直链会 503")
            print(f"      把 LX 音源 .js 放到 {source_dir} 后重启该容器")

    print(
        f"  NagaAgent 问答    {'已开启（外部网关保持关闭）' if nagaagent_enabled else '未开启'}"
    )

    print("-" * 68)
    print("后续步骤：")
    print(f"  1) QQ 登录：docker logs -f {NAPCAT_CONTAINER}  然后扫码")
    print("     （未登录时协议端不会监听 3001，本体连不上属正常）")
    print(f"  {catalog.MODEL_REMINDER}")
    print("  2) 状态/日志：uv run deploy status | uv run deploy logs")
    print(f"  3) 停止：uv run deploy down（数据保留在 {layout.root}）")
    print("=" * 68)


# --------------------------------------------------------------------------- #
# 写盘
# --------------------------------------------------------------------------- #


def write_generated(
    layout: DeployLayout, config: generate.GeneratedConfiguration
) -> None:
    """把生成结果落盘（凭据文件权限 0600）。"""
    layout.ensure()
    write_text(layout.env_file, generate.render_env(config.env), secret=True)
    write_text(layout.compose_file, config.compose_text)
    if config.searxng_settings is not None:
        write_text(layout.searxng_dir / "settings.yml", config.searxng_settings)
    if config.firecrawl_env is not None:
        write_text(layout.firecrawl_dir / ".env", config.firecrawl_env, secret=True)
    if config.lxmusic2api_config is not None:
        write_text(layout.lxmusic2api_dir / "config.toml", config.lxmusic2api_config)
        layout.lxmusic2api_private_dir.mkdir(parents=True, exist_ok=True)


def patch_napcat_ws_token(layout: DeployLayout, token: str) -> str:
    """把 WS token 写进 NapCat 生成的 ``onebot11.json``。

    NapCat 容器启动后才生成该文件；模板里 token 为空，不补的话协议端会以
    「无 token」监听，而本体侧带着 token 去连会被拒。返回处理结果供日志展示。
    """
    if not token:
        return "跳过：token 为空"
    path = layout.napcat_config_dir / NAPCAT_ONEBOT_CONFIG
    if not path.is_file():
        return f"跳过：{path} 尚未生成（等 NapCat 首次启动后再跑 up 即可）"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"跳过：{path} 无法解析（{exc}）"
    if not isinstance(data, dict):
        return f"跳过：{path} 结构不是对象"

    network = data.get("network")
    if not isinstance(network, dict):
        return f"跳过：{path} 缺少 network 段"
    servers = network.get("websocketServers")
    if not isinstance(servers, list) or not servers:
        return f"跳过：{path} 未启用正向 WebSocket 服务端"

    changed = False
    for server in servers:
        if isinstance(server, dict) and server.get("token") != token:
            server["token"] = token
            changed = True
    if not changed:
        return f"已是目标 token：{path}"

    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n", secret=True)
    return f"已对齐 WS token：{path}"


def build_invocation(
    layout: DeployLayout, project_name: str
) -> docker_cli.ComposeInvocation:
    return docker_cli.ComposeInvocation(
        compose_file=layout.compose_file,
        env_file=layout.env_file,
        project_name=project_name,
    )


# --------------------------------------------------------------------------- #
# up
# --------------------------------------------------------------------------- #


def run_up(options: dict[str, Any]) -> int:
    repo = repo_root()
    layout = DeployLayout.under(repo)
    dry_run = bool(options.get("dry_run"))
    wizard = Wizard(enabled=wizard_enabled(options))

    previous_env = load_previous_env(layout)
    previous_state = read_state(layout)

    default_mode = str(
        options.get("mode")
        or (previous_state.mode if previous_state else None)
        or catalog.DEFAULTS["mode"]
    )
    mode = wizard.choose_mode(default_mode)

    if options.get("services"):
        services = tuple(options["services"])
    elif wizard.enabled:
        services = wizard.choose_services(
            previous_state.services if previous_state else ()
        )
    else:
        services = tuple(previous_state.services) if previous_state else ()

    if options.get("nagaagent") is None:
        nagaagent_enabled = wizard.choose_nagaagent(
            previous_state.nagaagent if previous_state else False
        )
    else:
        nagaagent_enabled = bool(options["nagaagent"])

    port_bind = options.get("port_bind") or wizard.choose_port_bind(
        str(catalog.DEFAULTS["port_bind"])
    )

    # 子模块必须先就绪：能力开关与目标代码由同一问决定
    if nagaagent_enabled and not dry_run:
        try:
            result = nagaagent.ensure_submodule(repo)
        except RuntimeError as exc:
            print(f"错误：{exc}")
            return EXIT_ERROR
        print(
            "NagaAgent 子模块："
            + ("已就绪" if result == "already-ready" else "拉取完成")
        )

    ports = dict(catalog.port_defaults())
    ports.update(options.get("port_overrides") or {})
    existing_config = config_patch.load_toml(repo / "config.toml")

    ctx = generate.GenerateContext(
        repo=repo,
        layout=layout,
        mode=mode,
        services=services,
        nagaagent=nagaagent_enabled,
        ports=ports,
        port_bind=port_bind,
        image_owner=images.resolve_image_owner(),
        version=images.resolve_project_version(repo),
        previous_env=previous_env,
        existing_config=existing_config,
    )

    try:
        config = generate.build(ctx)
    except generate.GenerateError as exc:
        print(f"错误：{exc}")
        return EXIT_ERROR

    plan = config_patch.merge_plans(
        config.patch_plan,
        nagaagent.build_patch_plan(repo, nagaagent=nagaagent_enabled),
    )

    print("部署计划：")
    print(f"  部署模式：{mode}")
    print(
        "  额外服务：" + (", ".join(services) if services else "无（仅本体 + NapCat）")
    )
    print(f"  端口绑定：{port_bind}")
    describe_patch_plan(plan, existing_config)

    if not dry_run and wizard.enabled:
        if not wizard.confirm("\n按以上计划继续？", True):
            print("已取消，未改动任何文件。")
            return EXIT_OK

    project_name = (
        previous_state.project_name if previous_state else catalog.COMPOSE_PROJECT_NAME
    )
    runner: Runner = DryRunRunner() if dry_run else docker_cli.CommandRunner()

    # 写盘：先配置后 compose，任何一步失败都不会留下「compose 指向旧配置」的状态
    try:
        outcome = config_patch.apply_plan(
            plan,
            example_path=repo / "config.toml.example",
            backup_dir=layout.backup_dir,
            dry_run=dry_run,
        )
    except config_patch.ConfigError as exc:
        print(f"错误：{exc}")
        return EXIT_ERROR
    if dry_run:
        print(
            f"config.toml：将写入 {len(outcome.changed_keys)} 项"
            if outcome.changed_keys
            else "config.toml：无需变更"
        )
    elif outcome.written:
        print(f"config.toml：已更新 {len(outcome.changed_keys)} 项", end="")
        if outcome.backup_path is not None:
            print(f"（备份：{outcome.backup_path}）")
        else:
            print()
    else:
        print("config.toml：无变更")

    if dry_run:
        # dry-run 不落盘，只把将生成的内容打印出来
        print("\n--- compose.yaml（将写入 deploy/compose.yaml）---")
        print(config.compose_text)
        print("--- .env（凭据已省略）---")
        print(
            generate.render_env(
                {
                    key: ("<secret>" if _looks_secret(key) else value)
                    for key, value in config.env.items()
                }
            )
        )
        print(dry_run_runner_commands(runner))
        return EXIT_OK

    write_generated(layout, config)

    invocation = build_invocation(layout, project_name)
    availability = docker_cli.check_availability()
    if not availability.ok:
        print(f"错误：{availability.describe()}")
        return EXIT_ERROR

    validation = docker_cli.compose_config(runner, invocation)
    if not validation.ok:
        print(f"错误：生成的 compose 未通过校验：{validation.summary()}")
        return EXIT_ERROR

    pull = str(options.get("pull") or docker_cli.PULL_MISSING)
    print(f"\n启动服务（镜像拉取策略：{pull}）…")
    up_result = docker_cli.compose_up(runner, invocation, pull=pull)
    if not up_result.ok:
        print(f"错误：docker compose up 失败：{up_result.summary()}")
        print(up_result.combined_output())
        return EXIT_ERROR

    token_note = patch_napcat_ws_token(layout, config.napcat_ws_token)
    print(f"NapCat 配置：{token_note}")

    save_state(
        layout,
        DeployState(
            services=services,
            mode=mode,
            nagaagent=nagaagent_enabled,
            ports={
                spec.key: ctx.port(spec.key) for spec in catalog.port_specs().values()
            },
            image_owner=ctx.image_owner,
            project_name=project_name,
        ),
    )

    print_access_summary(
        layout,
        config.env,
        mode=mode,
        services=services,
        nagaagent_enabled=nagaagent_enabled,
    )
    if _any_port_exposed(config.env):
        print(
            "⚠ 检测到有端口绑定到 0.0.0.0：WebUI / NapCat / Firecrawl 均无强鉴权，"
            "请确认已在防火墙或反向代理后。"
        )
    return EXIT_OK


def _looks_secret(key: str) -> bool:
    lowered = key.lower()
    return any(
        marker in lowered
        for marker in ("token", "password", "secret", "auth_key", "api_key")
    )


def _any_port_exposed(env: dict[str, str]) -> bool:
    return any(
        value in ("0.0.0.0", "::")
        for key, value in env.items()
        if key.endswith("_BIND")
    )


def dry_run_runner_commands(runner: Runner) -> str:
    if isinstance(runner, DryRunRunner) and runner.commands:
        return "--- 将执行的命令 ---\n" + "\n".join(
            "  " + " ".join(command) for command in runner.commands
        )
    return "--- 将执行的命令 ---\n  （无）"


# --------------------------------------------------------------------------- #
# down / status / logs
# --------------------------------------------------------------------------- #


def _require_layout(
    require_state: bool = True,
) -> tuple[DeployLayout, DeployState] | None:
    repo = repo_root()
    layout = DeployLayout.under(repo)
    if not layout.compose_file.is_file():
        print(f"错误：{layout.compose_file} 不存在，请先执行 uv run deploy up")
        return None
    state = read_state(layout)
    if state is None:
        if require_state:
            print(f"错误：{layout.state_file} 缺失或不可识别，请重新执行 up")
            return None
        state = DeployState()
    return layout, state


def run_down(options: dict[str, Any]) -> int:
    found = _require_layout()
    if found is None:
        return EXIT_ERROR
    layout, state = found

    purge = bool(options.get("purge"))
    remove_volumes = bool(options.get("volumes")) or purge
    if purge:
        print("⚠ --purge 会删除容器数据与凭据，且不可恢复。")

    runner = docker_cli.CommandRunner()
    result = docker_cli.compose_down(
        runner,
        build_invocation(layout, state.project_name),
        remove_volumes=remove_volumes,
    )
    if not result.ok:
        print(f"错误：docker compose down 失败：{result.summary()}")
        return EXIT_ERROR

    print("服务已停止。")
    if purge:
        import shutil

        shutil.rmtree(layout.root, ignore_errors=True)
        print(f"已删除 {layout.root}")
    else:
        print(f"数据与配置保留在 {layout.root}")
    return EXIT_OK


def run_status(options: dict[str, Any]) -> int:
    del options
    found = _require_layout()
    if found is None:
        return EXIT_ERROR
    layout, state = found
    env = load_previous_env(layout)

    runner = docker_cli.CommandRunner()
    availability = docker_cli.check_availability()
    if availability.ok:
        ps = docker_cli.compose_ps(runner, build_invocation(layout, state.project_name))
        if ps.ok:
            _print_ps(ps.stdout)
        else:
            print(f"（docker compose ps 失败：{ps.summary()}）")
    else:
        print(f"（{availability.describe()}）")

    print_access_summary(
        layout,
        env,
        mode=state.mode or catalog.MODE_CONTAINER,
        services=state.services,
        nagaagent_enabled=state.nagaagent,
    )
    return EXIT_OK


def _print_ps(payload: str) -> None:
    """把 ``docker compose ps --format json`` 的结果整理成表格。"""
    text = payload.strip()
    if not text:
        print("（没有运行中的服务）")
        return
    rows: list[dict[str, Any]] = []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # compose 也可能逐行输出 JSON 对象
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    else:
        if isinstance(parsed, list):
            rows = [item for item in parsed if isinstance(item, dict)]
        elif isinstance(parsed, dict):
            rows = [parsed]

    if not rows:
        print(text)
        return

    print("容器状态：")
    for row in rows:
        name = str(row.get("Service") or row.get("Name") or "?")
        status = str(row.get("Status") or row.get("State") or "?")
        health = str(row.get("Health") or "").strip()
        suffix = f"（{health}）" if health else ""
        print(f"  {name:<20} {status}{suffix}")


def run_logs(options: dict[str, Any]) -> int:
    found = _require_layout()
    if found is None:
        return EXIT_ERROR
    layout, state = found

    services = tuple(options.get("services") or ())
    runner = docker_cli.CommandRunner()
    result = docker_cli.compose_logs(
        runner,
        build_invocation(layout, state.project_name),
        services=services,
        tail=options.get("tail"),
        follow=True,
    )
    if not result.ok:
        print(f"错误：docker compose logs 失败：{result.summary()}")
        return EXIT_ERROR
    return EXIT_OK


__all__ = [
    "NAPCAT_CONTAINER",
    "NAPCAT_ONEBOT_CONFIG",
    "Wizard",
    "build_invocation",
    "describe_patch_plan",
    "load_previous_env",
    "parse_env_text",
    "patch_napcat_ws_token",
    "print_access_summary",
    "run_down",
    "run_logs",
    "run_status",
    "run_up",
    "wizard_enabled",
    "write_generated",
]
