from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from Undefined.skills.agents.code_delivery_agent.tools.end.handler import execute
from Undefined.utils import io as async_io
from Undefined.utils.message_targets import DeliveryAddress
from Undefined.utils.sender import AddressBoundSender, MessageSender


@pytest.mark.asyncio
async def test_code_delivery_uses_current_wechat_route(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    task_dir = tmp_path / "task"
    await async_io.ensure_dir(workspace)
    await async_io.ensure_dir(task_dir)
    await async_io.write_text(workspace / "result.txt", "done")

    onebot = MagicMock()
    onebot.upload_private_file = AsyncMock()
    onebot.send_private_message = AsyncMock()
    history = MagicMock()
    history.add_private_message = AsyncMock()
    config = SimpleNamespace(
        code_delivery_default_archive_format="zip",
        code_delivery_max_archive_size_mb=200,
        is_group_allowed=lambda _target_id: True,
        is_private_allowed=lambda _target_id: True,
        access_control_enabled=lambda: False,
        group_access_denied_reason=lambda _target_id: None,
        private_access_denied_reason=lambda _target_id: None,
    )
    sender = MessageSender(
        onebot,
        history,
        bot_qq=10000,
        config=config,  # type: ignore[arg-type]
    )
    service = SimpleNamespace(
        send_file=AsyncMock(return_value="client-file"),
        send_text=AsyncMock(return_value="client-summary"),
    )
    sender.set_weixin_service(service)
    bound_sender = AddressBoundSender(sender, DeliveryAddress("wechat", 12345))
    context: dict[str, Any] = {
        "workspace": workspace,
        "task_dir": task_dir,
        "config": config,
        "runtime_config": config,
        "target_type": "private",
        "target_id": 12345,
        "sender": bound_sender,
        "onebot_client": onebot,
    }

    result = await execute(
        {
            "exclude_patterns": [],
            "archive_name": "delivery",
            "summary": "测试完成",
        },
        context,
    )

    assert "状态: 上传成功" in result
    service.send_file.assert_awaited_once()
    assert service.send_file.await_args is not None
    assert service.send_file.await_args.args[0] == 12345
    assert service.send_file.await_args.kwargs["name"] == "delivery.zip"
    service.send_text.assert_awaited_once()
    onebot.upload_private_file.assert_not_awaited()
    onebot.send_private_message.assert_not_awaited()
    assert context["conversation_ended"] is True
