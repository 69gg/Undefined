"""通过官方配对 API 生成渠道私有 state，不启动第二个网络客户端。"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib
import socket
from pathlib import Path

from Undefined.config.models import ChiliarchConfig
from Undefined.utils import io


async def pair(
    server_url: str,
    code: str,
    name: str,
    machine: str,
    state: Path,
    introduction: str,
) -> None:
    native = importlib.import_module("chiliarch.client")
    adapter = importlib.import_module("chiliarch.adapters.runtime")
    state = state.expanduser().resolve()
    async with adapter.connection_owner(state):
        if await io.exists(state):
            raise ValueError("state 已存在，请选择新文件，避免覆盖凭证和持久任务")
        await native.AgentClient.pair(
            server_url,
            code,
            name,
            machine,
            state,
            capabilities=[
                "chiliarch.tasks",
                "chiliarch.contacts",
                "chiliarch.requests",
                "adapter.undefined",
            ],
            introduction=introduction,
        )


def run() -> None:
    defaults = ChiliarchConfig()
    parser = argparse.ArgumentParser(description="配对 Undefined chiliarch 原生渠道")
    parser.add_argument("--server", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--state", type=Path, default=Path(defaults.state_path))
    parser.add_argument("--machine", default=socket.gethostname())
    parser.add_argument("--introduction", default=defaults.introduction)
    args = parser.parse_args()
    try:
        asyncio.run(
            pair(
                args.server,
                getpass.getpass("一次性注册码: "),
                args.name,
                args.machine,
                args.state,
                args.introduction,
            )
        )
    except Exception as exc:
        # 参数或网络异常可能包含密钥，只展示类型与恢复方式。
        parser.exit(
            1,
            f"配对未完成（{type(exc).__name__}）。检查可选依赖、地址、注册码及state是否已存在。\n",
        )
    print(f"配对完成，凭证保存在 {args.state.resolve()}；启动 Undefined 接管该state。")
