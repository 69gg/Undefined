"""``uv run deploy`` 的命令行入口。

职责仅限：解析参数、收集配置（交互向导或参数/状态文件）、分发到子命令。
真正的渲染与 docker 调用在 ``generate`` / ``config_patch`` / ``docker_cli`` 里，
本模块不直接触碰文件系统与外部进程。
"""

from __future__ import annotations

import argparse
from typing import Sequence

from Undefined.deploy import catalog
from Undefined.deploy.catalog import EXIT_ERROR, EXIT_OK
from Undefined.deploy.docker_cli import PULL_POLICIES

PROGRAM = "deploy"

#: 子命令名，用于 ``--help`` 与错误提示。
SUBCOMMANDS = ("up", "down", "status", "logs")


def build_parser() -> argparse.ArgumentParser:
    """构造参数解析器。

    端口与模式等取值全部走参数/状态文件，代码里不写死（除 ``catalog.DEFAULTS``
    这份唯一默认值表）。
    """
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "一次性容器化部署：拉起 Undefined 本体与 NapCat，"
            "并按需部署 SearXNG / Firecrawl / lxmusic2api。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  uv run deploy up                      # 交互式向导\n"
            "  uv run deploy up --yes                # 全部默认（本体 + NapCat）\n"
            "  uv run deploy up --with searxng       # 额外部署 SearXNG\n"
            "  uv run deploy up --mode host          # 本体跑宿主机，只容器化依赖服务\n"
            "  uv run deploy up --with-nagaagent     # 同时拉取 NagaAgent 子模块并开启其问答能力\n"
            "  uv run deploy status                  # 查看入口地址与凭据\n"
        ),
    )
    parser.add_argument(
        "--version", action="version", version=_version_string(), help="显示版本并退出"
    )

    subparsers = parser.add_subparsers(
        dest="command", metavar="{" + ",".join(SUBCOMMANDS) + "}"
    )

    up = subparsers.add_parser("up", help="生成配置并启动服务（幂等）")
    _add_common_options(up)
    up.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要写入的 config.toml 变更与生成的 compose，不落盘、不启动容器",
    )
    up.add_argument(
        "--pull",
        choices=PULL_POLICIES,
        default=None,
        help=(
            "镜像拉取策略，默认 missing（本地没有才拉）。"
            "always=总是检查更新；never=完全不拉（离线）"
        ),
    )

    down = subparsers.add_parser("down", help="停止服务（默认保留数据）")
    down.add_argument(
        "--purge",
        action="store_true",
        help="同时删除 deploy/ 下的数据与凭据（不可恢复）",
    )
    down.add_argument(
        "--volumes",
        action="store_true",
        help="同时删除 compose 管理的 named volumes（SearXNG 缓存、Firecrawl 数据）",
    )

    subparsers.add_parser("status", help="显示服务状态、入口地址与凭据")

    logs = subparsers.add_parser("logs", help="跟踪服务日志")
    logs.add_argument(
        "services",
        nargs="*",
        help="只显示这些服务的日志（默认全部），如 napcat undefined-bot",
    )
    logs.add_argument(
        "--tail",
        type=int,
        default=None,
        metavar="N",
        help="只显示最近 N 行",
    )

    return parser


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    """``up`` 的部署选择项。"""
    parser.add_argument(
        "--mode",
        choices=catalog.DEPLOY_MODES,
        default=None,
        help=(
            "本体部署方式：container=本体也在 compose 里（默认）；"
            "host=本体跑在宿主机，只用 Docker 跑依赖服务"
        ),
    )
    parser.add_argument(
        "--with",
        dest="services",
        default=None,
        metavar="SVC[,SVC...]",
        help=(
            "额外部署的自托管服务，逗号分隔，默认全部不部署。可选："
            + ", ".join(service.key for service in catalog.OPTIONAL_SERVICES)
        ),
    )
    for service in catalog.OPTIONAL_SERVICES:
        parser.add_argument(
            f"--with-{service.key}",
            dest="service_flags",
            action="append_const",
            const=service.key,
            default=None,
            help=f"等价于 --with {service.key}（{service.label}）",
        )

    naga = parser.add_mutually_exclusive_group()
    naga.add_argument(
        "--with-nagaagent",
        dest="nagaagent",
        action="store_true",
        default=None,
        help="拉取 code/NagaAgent 子模块并开启 NagaAgent 问答能力（不开启外部网关）",
    )
    naga.add_argument(
        "--no-nagaagent",
        dest="nagaagent",
        action="store_false",
        default=None,
        help="不拉取 NagaAgent 子模块，并关闭全部 Naga 相关配置（默认）",
    )

    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="不进入交互向导，未指定的项一律使用默认值",
    )
    parser.add_argument(
        "--port",
        dest="port_overrides",
        action="append",
        default=None,
        metavar="KEY=PORT",
        help=("覆盖端口，可重复。KEY 取：" + ", ".join(sorted(catalog.port_specs()))),
    )
    parser.add_argument(
        "--port-bind",
        dest="port_bind",
        default=None,
        metavar="ADDR",
        help=f"所有发布端口的绑定地址，默认 {catalog.DEFAULT_PORT_BIND}",
    )


def _version_string() -> str:
    from Undefined import __version__

    return f"{PROGRAM} (Undefined {__version__})"


def parse_ports(raw: Sequence[str] | None) -> dict[str, int]:
    """把 ``--port key=value`` 解析为字典，键必须是已知端口。"""
    specs = catalog.port_specs()
    ports: dict[str, int] = {}
    for item in raw or ():
        key, separator, value = item.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ValueError(f"--port 需要 KEY=PORT 形式，收到 {item!r}")
        if key not in specs:
            known = ", ".join(sorted(specs))
            raise ValueError(f"未知端口键 {key!r}；可选：{known}")
        try:
            port = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"--port {key} 的端口必须是整数，收到 {value!r}") from exc
        if not 1 <= port <= 65535:
            raise ValueError(f"--port {key}={port} 超出 1-65535")
        ports[key] = port
    return ports


def normalize_services(
    raw: str | Sequence[str] | None = None,
    extra: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """把 ``--with`` 与 ``--with-<svc>`` 归一化成有序、去重的服务 key 元组。"""
    items: list[str] = []
    if isinstance(raw, str):
        items.extend(part.strip() for part in raw.split(","))
    elif raw is not None:
        items.extend(str(part).strip() for part in raw)
    if extra:
        items.extend(str(part).strip() for part in extra)

    seen: dict[str, None] = {}
    for item in items:
        if not item:
            continue
        service = catalog.selected_service(item)
        seen.setdefault(service.key, None)
    return tuple(seen)


def main(argv: Sequence[str] | None = None) -> int:
    """命令入口；返回进程退出码。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return EXIT_OK

    normalized = dict(vars(args))
    # 部署选择项只挂在 up 上；其它子命令用 SUPPRESS 默认值，因此这里按需取。
    normalized["services"] = normalize_services(
        getattr(args, "services", None), getattr(args, "service_flags", None)
    )
    normalized["port_overrides"] = parse_ports(getattr(args, "port_overrides", None))

    try:
        from Undefined.deploy.commands import dispatch

        return dispatch(args.command, normalized)
    except KeyboardInterrupt:  # pragma: no cover - 交互终端中断
        print("\n已取消。")
        return EXIT_ERROR
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"错误：{exc}")
        return EXIT_ERROR


__all__: list[str] = [
    "SUBCOMMANDS",
    "build_parser",
    "main",
    "normalize_services",
    "parse_ports",
]
