"""原生 chiliarch 出站渠道：普通逻辑聊天、任务和持久关联的双向协作。"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from Undefined.api.webchat_store import WebChatConversationStore
from Undefined.attachments import (
    render_message_with_attachments,
    scope_from_context,
)
from Undefined.channels.session import run_logical_chat
from Undefined.ai.client.ask_loop import ChatExecutionError
from Undefined.utils import io
from Undefined.utils.message_targets import DeliveryAddress, parse_delivery_address
from Undefined.utils.paths import DATA_DIR

from .mailbox import RoutedMailbox
from .store import ChannelJournal

logger = logging.getLogger(__name__)
Progress = Callable[[float, str], Awaitable[None]]
DEFAULT_STATE_PATH = DATA_DIR / "chiliarch" / "client.db"
LOGICAL_IDENTITY = "chiliarch_main"
DISPLAY_NAME = "chiliarch 总管"
MAX_CONCURRENT_TASKS = 1
_PAIR_CHECK_SECONDS = 1.0
_INBOX_POLL_SECONDS = 0.2


def _key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _origin_key(origin: dict[str, Any]) -> str:
    return json.dumps(origin, sort_keys=True, ensure_ascii=False)


def capture_origin(context: dict[str, Any]) -> dict[str, Any]:
    """只记录可重建的投递身份，不保存回调、密钥或整份工具上下文。"""
    if context.get("logical_identity"):
        return {
            "kind": "logical",
            "identity": str(context["logical_identity"]),
            "conversation_id": str(context.get("logical_conversation_id") or "main"),
            "task_id": str(context.get("chiliarch_task_id") or ""),
        }
    if context.get("webui_session") and context.get("webchat_conversation_id"):
        return {
            "kind": "webui",
            "conversation_id": str(context["webchat_conversation_id"]),
        }
    address, error = parse_delivery_address(context.get("address"))
    if error:
        raise ValueError(error)
    if address is None:
        group_id = context.get("group_id")
        user_id = context.get("user_id") or context.get("sender_id")
        if group_id:
            address = DeliveryAddress("group", int(group_id))
        elif user_id:
            address = DeliveryAddress("qq", int(user_id))
    if address is not None:
        if address.target_id <= 0:
            raise ValueError("原会话地址无效")
        return {"kind": "physical", "address": address.canonical}
    raise ValueError("无法确定原聊天，拒绝创建无法回溯的协作请求")


class ChiliarchService:
    def __init__(self, runtime: Any, *, state_path: Path = DEFAULT_STATE_PATH) -> None:
        self.runtime = runtime
        self.state_path = state_path.expanduser().resolve()
        self.directory = self.state_path.with_name(self.state_path.name + ".undefined")
        self.journal = ChannelJournal(self.directory / "journal.json")
        self.history = WebChatConversationStore(
            directory=self.directory / "conversations",
            user_id=LOGICAL_IDENTITY,
            user_name=DISPLAY_NAME,
            migrate_legacy=False,
        )
        self.client: Any = None
        self._protocol: Any = None
        self._mailbox_type: Any = None
        self._task: asyncio.Task[None] | None = None
        self._started = asyncio.Event()
        self._paired = False
        self._state = "disabled"
        self._reason: str | None = None
        self._capacity = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self._download_locks: dict[str, asyncio.Lock] = {}
        self._local_tasks: dict[str, asyncio.Task[None]] = {}
        self._active: set[str] = set()
        self._progress: dict[str, Progress] = {}
        self._stopping = False

    def status(self) -> dict[str, Any]:
        """ready 只表示本地收件箱就绪；不推断网络在线或泄露配对凭证。"""
        return {
            "enabled": self._paired,
            "state": self._state,
            "reason": self._reason,
            "mailbox_ready": self._ready(),
            "transport_attempt": getattr(self.client, "transport", None),
            "logical_identity": LOGICAL_IDENTITY,
            "display_name": DISPLAY_NAME,
            "active_sessions": len(self._active),
            "capacity": MAX_CONCURRENT_TASKS,
            "supports_task_workdir": False,
        }

    def _ready(self) -> bool:
        return bool(
            self.client is not None
            and self._paired
            and self.client.ready.is_set()
            and not self._stopping
        )

    def runtime_metadata(self) -> dict[str, Any]:
        return {
            "client": "Undefined",
            "adapter": "undefined",
            "execution_mode": "managed",
            "state": "busy" if self._active else "idle",
            "local_active_sessions": len(self._active),
            "supports_task_workdir": False,
        }

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopping = False
        self._started.clear()
        self._task = asyncio.create_task(self._watch(), name="chiliarch.channel")
        await self._started.wait()

    async def _watch(self) -> None:
        """配对文件是唯一开关；运行中配对和删除均无需重启或修改主配置。"""
        try:
            while not self._stopping:
                self._paired = await io.is_file(self.state_path)
                if self._paired:
                    await self._run()
                    # 吊销或协议拒绝需要处理身份/协议，不能反复尝试或自行重新配对。
                    if self._reason in {"CredentialRejected", "ProtocolRejected"}:
                        await self._wait_for_unpair()
                else:
                    self._state = "disabled"
                    self._reason = None
                    self._started.set()
                await asyncio.sleep(_PAIR_CHECK_SECONDS)
        finally:
            self._started.set()

    async def _wait_for_unpair(self) -> None:
        while await io.is_file(self.state_path):
            await asyncio.sleep(_PAIR_CHECK_SECONDS)
        self._paired = False

    async def _run(self) -> None:
        network: asyncio.Task[None] | None = None
        listener: asyncio.Task[None] | None = None
        ready: asyncio.Task[bool] | None = None
        unpaired: asyncio.Task[None] | None = None
        owner: Any = None
        owned = False
        try:
            native = importlib.import_module("chiliarch.client")
            adapter = importlib.import_module("chiliarch.adapters.runtime")
            self._protocol = importlib.import_module("chiliarch.protocol")
            self._mailbox_type = importlib.import_module(
                "chiliarch.adapters.mailbox"
            ).AgentMailbox
            # 与官方 CLI/daemon 使用同一连接所有权锁，不能共用 state 启第二个连接。
            owner = adapter.connection_owner(self.state_path)
            await owner.__aenter__()
            owned = True
            self.client = await native.AgentClient.from_state(
                self.state_path,
                self._handle_task,
                max_concurrent_tasks=MAX_CONCURRENT_TASKS,
                runtime_metadata=self.runtime_metadata,
            )
            await self.client.store.open()
            try:
                identity = await self.client.store.identity()
            finally:
                await self.client.store.close()
            # 重新配对可以更换平台或 agent；旧回信关联不能进入新的身份。
            namespace = _key(self.client.server_url + ":" + str(identity["agent_id"]))
            self.journal = ChannelJournal(self.directory / namespace / "journal.json")
            unpaired = asyncio.create_task(self._wait_for_unpair())
            await self.journal.open()
            await self.history.ensure_ready()
            await self.history.create_conversation(conversation_id="main")
            network = asyncio.create_task(self.client.run(), name="chiliarch.native")
            ready = asyncio.create_task(self.client.ready.wait())
            done, _ = await asyncio.wait(
                {network, ready, unpaired}, return_when=asyncio.FIRST_COMPLETED
            )
            if unpaired in done:
                unpaired.result()
                return
            if network in done:
                network.result()
                raise RuntimeError("native client stopped before mailbox readiness")
            for route in list(self.journal.data["routes"].values()):
                if route["state"] == "prepared":
                    await self._enqueue_route(route)
            for event_id, event in list(self.journal.data["events"].items()):
                if event.get("state") == "queued":
                    self._start_local(event_id)
            self._state = "running"
            self._reason = None
            self._started.set()
            listener = asyncio.create_task(self._listen(), name="chiliarch.inbox")
            done, _ = await asyncio.wait(
                {network, listener, unpaired}, return_when=asyncio.FIRST_COMPLETED
            )
            for finished in done:
                finished.result()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._state = "unavailable"
            self._reason = type(exc).__name__
            # 异常正文可能含 URL/鉴权数据；日志和状态只报告类型。
            logger.warning("[chiliarch] 渠道不可用: %s", self._reason)
        finally:
            self._started.set()
            if self.client is not None:
                self.client.stop()
            tasks: list[asyncio.Task[Any]] = [*self._local_tasks.values()]
            tasks.extend(
                item
                for item in (listener, ready, network, unpaired)
                if item is not None
            )
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.history.stop()
            try:
                self.client = None
                self._paired = await io.is_file(self.state_path)
                if not self._paired:
                    if owned:
                        # 删除主文件后可能残留旧 WAL，新配对不能重放旧收件。
                        for suffix in ("-wal", "-shm"):
                            await io.delete_file(Path(f"{self.state_path}{suffix}"))
                    self._state = "disabled"
                    self._reason = None
                elif self._state != "unavailable":
                    self._state = "stopped"
            finally:
                if owned:
                    await owner.__aexit__(None, None, None)

    def stop_accepting_messages(self) -> None:
        self._stopping = True

    async def stop(self) -> None:
        self.stop_accepting_messages()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    def _require_ready(self) -> None:
        if not self._ready():
            raise RuntimeError("chiliarch 渠道收件箱不可用；检查配对文件和渠道状态")

    async def _enqueue_route(self, route: dict[str, Any]) -> str:
        envelope = self._protocol.Envelope.model_validate(route["envelope"])
        if envelope.type == "agent.request":
            request_id = await self.client.store.enqueue_request(
                envelope, route.get("client_request_id")
            )
        else:
            await self.client.store.enqueue(envelope)
            request_id = envelope.id
        route = {**route, "state": "enqueued"}
        await self.journal.put("routes", route["id"], route)
        return str(request_id)

    async def _send(
        self,
        kind: str,
        payload: dict[str, Any],
        origin: dict[str, Any],
        *,
        client_request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> str:
        self._require_ready()
        if (
            client_request_id is not None
            and not 1 <= len(client_request_id.strip()) <= 128
        ):
            raise ValueError("client_request_id 必须包含1到128个字符")
        route_id = (
            str(uuid5(NAMESPACE_URL, _origin_key(origin) + ":" + client_request_id))
            if client_request_id
            else str(uuid4())
        )
        fingerprint = json.dumps(
            {"type": kind, "payload": payload, "correlation_id": correlation_id},
            sort_keys=True,
            ensure_ascii=False,
        )

        # serializes concurrent retries of the same ID before the native outbox transaction.
        def reserve(data: dict[str, Any]) -> dict[str, Any]:
            old = data["routes"].get(route_id)
            if old is not None:
                if old["fingerprint"] != fingerprint:
                    raise ValueError("client_request_id 已用于不同内容")
                return dict(old)
            body = dict(payload)
            if kind == "agent.request":
                body["request_id"] = route_id
            envelope = self._protocol.Envelope(
                id=route_id,
                type=kind,
                correlation_id=route_id if kind == "agent.request" else correlation_id,
                payload=body,
            )
            route = {
                "id": route_id,
                "origin": origin,
                "fingerprint": fingerprint,
                "client_request_id": route_id if client_request_id else None,
                "envelope": envelope.model_dump(mode="json"),
                "state": "prepared",
                "notify": "artifact" not in str(payload.get("operation", "")),
            }
            data["routes"][route_id] = route
            return dict(route)

        route = await self.journal.update(reserve)
        if route["state"] == "prepared":
            return await self._enqueue_route(route)
        return route_id

    async def contact(
        self,
        message: str,
        *,
        origin: dict[str, Any],
        client_request_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        envelope_id = await self._send(
            "agent.contact",
            {"message": message, "metadata": metadata or {}},
            origin,
            client_request_id=client_request_id,
            correlation_id=correlation_id,
        )
        return {"status": "queued", "message_id": envelope_id}

    async def _validate_task(self, task_id: str | None) -> None:
        if task_id is None:
            return
        for state, command in await self.client.store.tasks():
            if str(command.payload["task_id"]) == task_id and state == "running":
                return
        raise ValueError("当前正式任务已停止，不能继续发起协作操作")

    async def request_operation(
        self,
        operation: str,
        arguments: dict[str, Any],
        *,
        origin: dict[str, Any],
        message: str = "",
        wait_seconds: float = 0,
        client_request_id: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        self._require_ready()
        if not 0 <= wait_seconds <= 30:
            raise ValueError("wait_seconds 必须在0到30秒之间")
        await self._validate_task(task_id)
        payload: dict[str, Any] = {
            "operation": operation,
            "arguments": arguments,
            "message": message,
        }
        if task_id:
            payload["metadata"] = {"task_id": task_id}
        request_id = await self._send(
            "agent.request", payload, origin, client_request_id=client_request_id
        )
        return await self.get_request_result(
            request_id, origin=origin, task_id=task_id, wait_seconds=wait_seconds
        )

    async def get_request_result(
        self,
        request_id: str,
        *,
        origin: dict[str, Any],
        task_id: str | None = None,
        wait_seconds: float = 0,
    ) -> dict[str, Any]:
        self._require_ready()
        route = self.journal.data["routes"].get(request_id)
        if route is None or route["origin"] != origin:
            raise ValueError("请求不属于当前聊天")
        return dict(
            await self._mailbox_type(
                self.client.store, managed_task=task_id
            ).get_request_result(request_id, wait_seconds)
        )

    async def _task_conversation(self, payload: dict[str, Any]) -> str:
        task_id = str(payload["task_id"])
        parameters = payload.get("parameters", {})
        context = (
            parameters.get("chiliarch_context", {})
            if isinstance(parameters, dict)
            else {}
        )
        predecessor = (
            context.get("continue_task_id") if isinstance(context, dict) else None
        )

        def resolve(data: dict[str, Any]) -> str:
            if task_id in data["tasks"]:
                return str(data["tasks"][task_id])
            if predecessor:
                if str(predecessor) not in data["tasks"]:
                    raise ValueError("续接任务没有本地会话记录")
                conversation = str(data["tasks"][str(predecessor)])
            else:
                conversation = "task_" + _key(task_id)
            data["tasks"][task_id] = conversation
            return conversation

        return await self.journal.update(resolve)

    async def _handle_task(
        self, payload: dict[str, Any], progress: Progress
    ) -> dict[str, Any]:
        if payload.get("workdir"):
            native = importlib.import_module("chiliarch.client")
            raise native.TaskExecutionError(
                "Undefined chiliarch 渠道不支持 task_workdir"
            )
        conversation_id = await self._task_conversation(payload)
        task_id = str(payload["task_id"])
        self._progress[task_id] = progress
        try:
            text = str(payload["instruction"])
            if payload.get("parameters"):
                text += "\n\n平台任务协作资料（保留各字段的来源）：\n" + json.dumps(
                    payload["parameters"], ensure_ascii=False
                )
            result = await self._chat(conversation_id, text, task_id=task_id)
            return {"reply": result, "conversation_id": conversation_id}
        except ChatExecutionError as exc:
            native = importlib.import_module("chiliarch.client")
            raise native.TaskExecutionError("Undefined 聊天执行失败") from exc
        finally:
            self._progress.pop(task_id, None)

    async def _chat(
        self,
        conversation_id: str,
        text: str,
        *,
        task_id: str | None = None,
        correlation_id: str | None = None,
        event_id: str | None = None,
    ) -> str:
        lock = self._conversation_locks.setdefault(conversation_id, asyncio.Lock())
        async with lock, self._capacity:
            if self._stopping:
                raise asyncio.CancelledError
            if event_id is not None:
                event = {**self.journal.data["events"][event_id], "state": "processing"}
                await self.journal.put("events", event_id, event)
            active_id = task_id or "chat:" + str(uuid4())
            self._active.add(active_id)
            context = {
                "logical_identity": LOGICAL_IDENTITY,
                "logical_conversation_id": conversation_id,
                "chiliarch_task_id": task_id,
            }
            delivered_outputs: list[str] = []

            async def output(message: str) -> None:
                rendered = await self._prepare_output(message, context)
                await self.contact(
                    rendered,
                    origin=capture_origin(context),
                    correlation_id=correlation_id,
                    metadata={"task_id": task_id} if task_id else {},
                )
                delivered_outputs.append(rendered)

            try:
                await run_logical_chat(
                    self.runtime,
                    store=self.history,
                    identity=LOGICAL_IDENTITY,
                    display_name=DISPLAY_NAME,
                    conversation_id=conversation_id,
                    text=text,
                    send_output=output,
                    extra_context=context,
                )
                return "\n".join(delivered_outputs)
            finally:
                self._active.discard(active_id)

    async def _prepare_output(self, message: str, context: dict[str, Any]) -> str:
        registry = getattr(self.runtime.ai, "attachment_registry", None)
        rendered = await render_message_with_attachments(
            message,
            registry=registry,
            scope_key=scope_from_context(context),
            strict=True,
        )
        files: list[str] = []
        if registry is None:
            return message
        for attachment in rendered.attachments:
            record = await registry.resolve_async(
                attachment["uid"], scope_from_context(context)
            )
            if record is None:
                raise ValueError("附件不属于当前会话")
            record = await registry.ensure_local_file(record)
            result = await self.invoke(
                "upload_artifact",
                {
                    "path": record.local_path,
                    "members": [],
                    "client_request_id": "attachment:" + record.uid,
                },
                context,
            )
            if result.get("status") != "completed":
                raise ValueError("共享文件上传尚未完成，请先查询原上传请求")
            artifact = result["artifact"]
            files.append(f"共享文件：{artifact['id']}（{record.display_name}）")
        return message + ("\n" + "\n".join(files) if files else "")

    async def _listen(self) -> None:
        while not self._stopping:
            messages = await self.client.store.messages(
                int(self.journal.data["cursor"]), 100
            )
            for seq, envelope in messages:
                await self._receive(seq, envelope)
            await asyncio.sleep(_INBOX_POLL_SECONDS)

    def _route_for(self, envelope: Any) -> dict[str, Any] | None:
        candidates = [
            envelope.correlation_id,
            envelope.payload.get("request_id"),
            envelope.payload.get("reply_to"),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            key = self.journal.data["aliases"].get(str(candidate), str(candidate))
            route = self.journal.data["routes"].get(key)
            if route:
                return dict(route)
        return None

    async def _receive(self, seq: int, envelope: Any) -> None:
        event_id = str(envelope.id)
        route = self._route_for(envelope)
        event = self.journal.data["events"].get(event_id)
        if event is None:
            event = {
                "seq": seq,
                "envelope": importlib.import_module(
                    "chiliarch.adapters.artifacts"
                ).public_result(envelope.model_dump(mode="json")),
                "state": "received",
                "origin": route["origin"] if route else None,
            }
            if (
                envelope.type == "agent.message"
                and route is None
                and not envelope.correlation_id
                and not envelope.payload.get("metadata", {}).get("task_id")
            ):
                event["state"] = "queued"
            await self.journal.put("events", event_id, event)
        if envelope.type == "request.resolved" and route:
            result = envelope.payload.get("result")
            if isinstance(result, dict):
                peer = result.get("message")
                alias = result.get("message_id") or (
                    peer.get("id") if isinstance(peer, dict) else None
                )
                if alias:
                    await self.journal.update(
                        lambda data: data["aliases"].__setitem__(
                            str(alias), route["id"]
                        )
                    )
        if event["state"] == "queued":
            self._start_local(event_id)
        elif event["state"] == "received":
            event = {**event, "state": "processing", "delivery": "pending"}
            await self.journal.put("events", event_id, event)
            if route is None or route.get("notify", True):
                await self._record_incoming(envelope, route)
            if (
                route
                and route.get("notify", True)
                and route["origin"].get("kind") != "logical"
            ):
                address, _ = parse_delivery_address(route["origin"].get("address"))
                if address is not None and address.channel in {"qq", "group"}:
                    # 等待时仍为 pending，取消或重启可以恢复；发起投递后不重放。
                    while not self.runtime.onebot.connection_status()["connected"]:
                        await asyncio.sleep(_INBOX_POLL_SECONDS)
                event["delivery"] = "processing"
                await self.journal.put("events", event_id, event)
                try:
                    await self._notify(route["origin"], self._incoming_text(envelope))
                    event["delivery"] = "delivered"
                except Exception as exc:
                    event["delivery"] = "uncertain"
                    event["delivery_error"] = type(exc).__name__
            event["state"] = "completed"
            await self.journal.put("events", event_id, event)
        await self.journal.update(lambda data: data.__setitem__("cursor", seq))

    def _start_local(self, event_id: str) -> None:
        if event_id not in self._local_tasks and not self._stopping:
            task = asyncio.create_task(
                self._local_chat(event_id), name="chiliarch.chat." + event_id
            )
            self._local_tasks[event_id] = task
            task.add_done_callback(lambda done: self._local_tasks.pop(event_id, None))

    async def _local_chat(self, event_id: str) -> None:
        event = dict(self.journal.data["events"][event_id])
        try:
            envelope = self._protocol.Envelope.model_validate(event["envelope"])
            await self._chat(
                "main",
                str(envelope.payload["message"]),
                correlation_id=envelope.id,
                event_id=event_id,
            )
            event["state"] = "completed"
        except asyncio.CancelledError:
            # 尚未获得容量的消息仍为 queued，可在下次启动处理。
            state = self.journal.data["events"][event_id]["state"]
            event["state"] = "interrupted" if state == "processing" else state
            raise
        except Exception as exc:
            event["state"] = "failed"
            event["error"] = type(exc).__name__
            logger.warning("[chiliarch] 普通聊天失败: %s", type(exc).__name__)
        finally:
            await self.journal.put("events", event_id, event)

    @staticmethod
    def _incoming_text(envelope: Any) -> str:
        if envelope.type == "request.resolved":
            return "[chiliarch 请求结果]\n" + json.dumps(
                envelope.payload, ensure_ascii=False
            )
        source = (
            envelope.payload.get("sender_agent_id")
            or envelope.payload.get("sender_role")
            or "总管"
        )
        return f"[chiliarch 来源：{source}]\n{envelope.payload.get('message', '')}"

    async def _record_incoming(
        self, envelope: Any, route: dict[str, Any] | None
    ) -> None:
        origin = route["origin"] if route else {}
        conversation = (
            str(origin.get("conversation_id") or "")
            if origin.get("kind") == "logical"
            else ""
        )
        task_id = envelope.payload.get("task_id") or envelope.payload.get(
            "metadata", {}
        ).get("task_id")
        if not conversation:
            conversation = str(self.journal.data["tasks"].get(str(task_id), "main"))
        await self.history.create_conversation(conversation_id=conversation)
        await self.history.append_message(
            conversation,
            role="user",
            text_content=self._incoming_text(envelope),
            display_name="chiliarch 协作资料",
            user_name="chiliarch 协作资料",
            message_id=f"msg_chiliarch_{_key(str(envelope.id))}",
        )

    async def _notify(self, origin: dict[str, Any], message: str) -> None:
        if origin["kind"] == "webui":
            store = getattr(self.runtime, "webchat_store", None)
            if store is None:
                raise RuntimeError("WebUI 会话存储暂不可用，回信已保留")
            if await store.get_conversation(origin["conversation_id"]) is None:
                raise ValueError("原 WebUI 会话已删除")
            await store.append_message(
                origin["conversation_id"],
                role="bot",
                text_content=message,
                display_name="Bot",
                user_name="Bot",
            )
            return
        address, error = parse_delivery_address(origin.get("address"))
        if address is None or error:
            raise ValueError("原会话地址无效")
        cfg = self.runtime.config_getter()
        if address.channel == "group":
            allowed = cfg.is_group_allowed(address.target_id)
        else:
            allowed = cfg.is_private_allowed(address.target_id)
        if not allowed:
            raise PermissionError("原聊天当前被访问控制拦截，回信已保留")
        await self.runtime.sender.send_address_message(address, message)

    async def invoke(
        self, action: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        result = await self._invoke(action, arguments, context)
        if action == "status":
            return result
        # 官方 file helpers 使用低层原始结果；模型工具永远只看公共元数据。
        return dict(
            importlib.import_module("chiliarch.adapters.artifacts").public_result(
                result
            )
        )

    async def _invoke(
        self, action: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        if action == "status":
            return self.status()
        self._require_ready()
        origin = capture_origin(context)
        task_id = str(context.get("chiliarch_task_id") or "") or None
        mailbox = RoutedMailbox(self, origin, task_id)
        args = dict(arguments)
        if action in {
            "contact",
            "request",
            "send_peer_message",
            "create_channel",
            "wait_for_tasks",
            "acknowledge_peer_message",
            "upload_artifact",
        } and not args.get("client_request_id"):
            raise ValueError(
                "有副作用的操作必须提供稳定 client_request_id，重试沿用原ID"
            )
        if action == "contact":
            await self._validate_task(task_id)
            return await self.contact(
                str(args["message"]),
                origin=origin,
                client_request_id=args.get("client_request_id"),
                correlation_id=args.get("correlation_id"),
                metadata={"task_id": task_id} if task_id else {},
            )
        if action == "get_result":
            return await self.get_request_result(
                str(args["request_id"]),
                origin=origin,
                task_id=task_id,
                wait_seconds=float(args.get("wait_seconds", 0)),
            )
        if action == "read_messages":
            after = int(
                args.get(
                    "after", self.journal.data["cursors"].get(_origin_key(origin), 0)
                )
            )
            limit = int(args.get("limit", 100))
            result = await self._mailbox_type(
                self.client.store, managed_task=task_id
            ).read_messages(after=after, limit=limit)
            filtered = []
            for raw in result["messages"]:
                envelope = self._protocol.Envelope.model_validate(
                    {key: value for key, value in raw.items() if key != "seq"}
                )
                route = self._route_for(envelope)
                if (route and route["origin"] == origin) or (
                    not route and origin["kind"] == "logical"
                ):
                    filtered.append(raw)
            return {**result, "messages": filtered}
        if action == "acknowledge_messages":
            cursor = int(args["cursor"])
            if cursor < 0:
                raise ValueError("cursor 不能为负数")
            await self.journal.update(
                lambda data: data["cursors"].__setitem__(_origin_key(origin), cursor)
            )
            return {"cursor": cursor}
        if action == "progress":
            if task_id is None or task_id not in self._progress:
                raise ValueError("当前不在正式任务中")
            await self._progress[task_id](
                float(args["progress"]), str(args.get("message", ""))
            )
            return {"status": "queued"}
        if action == "upload_artifact":
            helper = importlib.import_module("chiliarch.adapters.artifacts")
            await self._validate_task(task_id)
            return dict(
                await helper.upload_artifact(
                    mailbox,
                    str(args["path"]),
                    args.get("members", []),
                    goal_id=args.get("goal_id"),
                    task_id=task_id,
                    client_request_id=args.get("client_request_id"),
                    timeout_seconds=float(args.get("timeout_seconds", 20)),
                )
            )
        if action == "download_artifact":
            return await self._download_artifact(args, context, mailbox, task_id)
        if action == "request":
            return await mailbox.request_operation(
                str(args["operation"]),
                dict(args.get("arguments", {})),
                message=str(args.get("message", "")),
                wait_seconds=float(args.get("wait_seconds", 0)),
                client_request_id=args.get("client_request_id"),
            )
        operations = {
            "list_agents",
            "create_channel",
            "list_channels",
            "get_channel",
            "send_peer_message",
            "acknowledge_peer_message",
            "get_peer_message",
            "wait_for_tasks",
            "list_task_waits",
        }
        if action not in operations:
            raise ValueError("未知 chiliarch 操作")
        wait = float(args.pop("wait_seconds", 0))
        request_key = args.pop("client_request_id", None)
        if action in {"send_peer_message", "wait_for_tasks", "list_task_waits"}:
            if args.get("task_id") not in {None, task_id}:
                raise ValueError("不能替其他任务发起协作")
            args["task_id"] = task_id
        if action == "send_peer_message":
            args.setdefault("wake", False)
        return await mailbox.request_operation(
            action, args, wait_seconds=wait, client_request_id=request_key
        )

    async def _download_artifact(
        self,
        args: dict[str, Any],
        context: dict[str, Any],
        mailbox: RoutedMailbox,
        task_id: str | None,
    ) -> dict[str, Any]:
        helper = importlib.import_module("chiliarch.adapters.artifacts")
        artifact_id = str(args["artifact_id"])
        scope = scope_from_context(context)
        if scope is None:
            raise ValueError("当前聊天没有附件作用域")
        directory = self.directory / "artifacts" / _key(scope)
        await io.ensure_dir(directory)
        timeout = float(args.get("timeout_seconds", 20))
        if not 0 < timeout <= 30:
            raise ValueError("timeout_seconds 必须大于0且不超过30秒")
        lock = self._download_locks.setdefault(
            scope + ":" + artifact_id, asyncio.Lock()
        )
        async with lock:
            manifest = await mailbox.request_operation(
                "get_artifact", {"artifact_id": artifact_id}, wait_seconds=timeout
            )
            if manifest.get("status") != "approved":
                return manifest
            artifact = manifest["result"]["artifact"]
            if artifact["state"] != "ready":
                raise ValueError("共享文件尚未就绪")
            destination = directory / _key(artifact_id + ":" + artifact["sha256"])
            # 已缓存文件也必须与平台当前大小和摘要一致；首次下载交给原生助手校验。
            if await io.exists(destination):
                content = await io.read_bytes(destination)
                if (
                    len(content) != artifact["size"]
                    or hashlib.sha256(content).hexdigest() != artifact["sha256"]
                ):
                    raise ValueError("共享文件缓存大小或SHA256校验失败")
                result = {
                    "status": "completed",
                    "artifact_id": artifact_id,
                    "destination": str(destination),
                    "sha256": artifact["sha256"],
                }
            else:
                result = await helper.download_artifact(
                    mailbox,
                    artifact_id,
                    str(destination),
                    task_id=task_id,
                    timeout_seconds=timeout,
                )
        if result.get("status") != "completed":
            return dict(result)
        registry = self.runtime.ai.attachment_registry
        record = await registry.register_local_file(
            scope,
            str(destination),
            kind="file",
            display_name=str(args.get("name") or artifact.get("name") or artifact_id),
            source_kind="chiliarch",
            source_ref=artifact_id,
        )
        return {
            **result,
            "attachment": f'<attachment uid="{record.uid}"/>',
            "uid": record.uid,
        }
