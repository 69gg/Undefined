"""为官方 artifact helpers 提供发送前持久关联 origin 的 Mailbox 接口。"""

from __future__ import annotations

from typing import Any


class RoutedMailbox:
    def __init__(
        self, service: Any, origin: dict[str, Any], task_id: str | None
    ) -> None:
        self.service = service
        self.origin = origin
        self.managed_task = task_id

    async def request_operation(
        self,
        operation: str,
        arguments: dict[str, Any],
        message: str = "",
        wait_seconds: float = 0,
        client_request_id: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        if task_id is not None and task_id != self.managed_task:
            raise ValueError("不能访问其他任务的收件箱")
        result = await self.service.request_operation(
            operation,
            arguments,
            message=message,
            wait_seconds=wait_seconds,
            client_request_id=client_request_id,
            origin=self.origin,
            task_id=self.managed_task,
        )
        return dict(result)

    async def get_request_result(
        self, request_id: str, wait_seconds: float = 0
    ) -> dict[str, Any]:
        result = await self.service.get_request_result(
            request_id,
            wait_seconds=wait_seconds,
            origin=self.origin,
            task_id=self.managed_task,
        )
        return dict(result)
