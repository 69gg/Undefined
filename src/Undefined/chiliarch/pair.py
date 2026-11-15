"""通过官方配对 API 生成渠道私有 state，不启动第二个网络客户端。"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import importlib
import logging
import socket
from pathlib import Path
from uuid import uuid4

from Undefined.utils import io

from .service import DEFAULT_STATE_PATH

logger = logging.getLogger(__name__)

DEFAULT_INTRODUCTION = "Undefined：具备独立聊天、记忆、侧写和工具的普通协作用户；支持消息、任务和共享文件，不支持指定任务工作目录。"


async def pair(
    server_url: str,
    code: str | None,
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
            raise ValueError("state 已存在，删除配对文件并等待渠道停用后才能重新配对")
        for suffix in ("-wal", "-shm"):
            await io.delete_file(Path(f"{state}{suffix}"))
        # 凭证写完并关闭 SQLite 后才发布正式文件，避免运行中的渠道读到半份配对。
        pending = state.with_name(f".{state.name}.{uuid4().hex}.pairing")
        exchanged = False
        published = False
        try:
            # 复用官方 URL 校验，不能先兑换注册码再发现地址格式无效。
            native.AgentClient(server_url, "", pending, introduction=introduction)
            pairing_code = (
                code
                if code is not None
                else await asyncio.to_thread(getpass.getpass, "一次性注册码: ")
            )

            async def exchange_and_publish() -> None:
                nonlocal exchanged, published
                await native.AgentClient.pair(
                    server_url,
                    pairing_code,
                    name,
                    machine,
                    pending,
                    capabilities=[
                        "chiliarch.tasks",
                        "chiliarch.contacts",
                        "chiliarch.requests",
                        "adapter.undefined",
                    ],
                    introduction=introduction,
                )
                exchanged = True
                await io.move_path(pending, state)
                published = True

            # 注册码只能兑换一次，取消也要先保存已兑换的凭证。
            await io.run_cancellation_safe(exchange_and_publish())
        finally:
            if not exchanged or published:
                for path in (pending, Path(f"{pending}-wal"), Path(f"{pending}-shm")):
                    await io.delete_file(path)
            else:
                logger.warning(
                    "[chiliarch] 配对文件发布失败，已兑换凭证及 SQLite 附属文件保留在 %s",
                    pending,
                )


def run() -> None:
    parser = argparse.ArgumentParser(description="配对 Undefined chiliarch 原生渠道")
    parser.add_argument("--server", required=True)
    parser.add_argument("--name", default="Undefined")
    parser.add_argument("--machine", default=socket.gethostname())
    parser.add_argument("--introduction", default=DEFAULT_INTRODUCTION)
    args = parser.parse_args()
    try:
        asyncio.run(
            pair(
                args.server,
                None,
                args.name,
                args.machine,
                DEFAULT_STATE_PATH,
                args.introduction,
            )
        )
    except Exception as exc:
        # 参数或网络异常可能包含密钥，只展示类型与恢复方式。
        parser.exit(
            1,
            f"配对未完成（{type(exc).__name__}）。检查平台地址、注册码及配对文件是否已存在。\n",
        )
    print(
        f"配对完成：{DEFAULT_STATE_PATH.resolve()}。Undefined 会自动检测并接入，无需修改配置。"
    )
