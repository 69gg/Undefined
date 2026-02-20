"""OneBot WebSocket 客户端"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Coroutine
from datetime import datetime

import websockets
from websockets.asyncio.client import ClientConnection

from Undefined.context import RequestContext
from Undefined.utils.logging import log_debug_json, redact_string, sanitize_data

logger = logging.getLogger(__name__)


def _mark_message_sent_this_turn() -> None:
    ctx = RequestContext.current()
    if ctx is None:
        return
    ctx.set_resource("message_sent_this_turn", True)


class OneBotClient:
    """OneBot v11 WebSocket 客户端"""

    def __init__(self, ws_url: str, token: str = ""):
        self.ws_url = ws_url
        self.token = token
        self.ws: ClientConnection | None = None
        self._message_id = 0
        self._pending_responses: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._message_handler: (
            Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None
        ) = None
        self._running = False

    def set_message_handler(
        self, handler: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> None:
        """设置消息处理器"""
        self._message_handler = handler

    async def connect(self) -> None:
        """连接到 OneBot WebSocket"""
        # 构建带 token 的 URL
        url = self.ws_url
        if self.token:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}access_token={self.token}"

        safe_ws_url = redact_string(self.ws_url)
        logger.info(
            f"[bold cyan][WebSocket][/bold cyan] 正在连接到 [blue]{safe_ws_url}[/blue]..."
        )

        # 同时在请求头中传递 token（兼容不同实现）
        extra_headers = {}
        if self.token:
            extra_headers["Authorization"] = f"Bearer {self.token}"

        try:
            self.ws = await websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=480,
                max_size=100 * 1024 * 1024,  # 100MB，支持大量历史消息
                additional_headers=extra_headers if extra_headers else None,
            )
            logger.info("[bold green][WebSocket][/bold green] 连接成功")
        except Exception as e:
            logger.error(f"[WebSocket] 连接失败: {e}")
            raise

    async def disconnect(self) -> None:
        """断开连接"""
        self._running = False
        if self.ws:
            logger.info("[WebSocket] 正在主动断开连接...")
            await self.ws.close()
            self.ws = None
            logger.info("[WebSocket] 连接已断开")

    async def _call_api(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        suppress_error_retcodes: set[int] | None = None,
    ) -> dict[str, Any]:
        """调用 OneBot API"""
        if not self.ws:
            raise RuntimeError("WebSocket 未连接")

        self._message_id += 1
        echo = str(self._message_id)  # 使用字符串类型

        request = {
            "action": action,
            "params": params or {},
            "echo": echo,
        }

        safe_params = sanitize_data(params or {})
        logger.debug(
            f"[bold yellow][API请求][/bold yellow] [green]{action}[/green] (ID=[magenta]{echo}[/magenta]) | 参数: {safe_params}"
        )
        if logger.isEnabledFor(logging.DEBUG):
            log_debug_json(logger, "[OneBot请求体]", request)

        # 创建 Future 等待响应
        future: asyncio.Future[dict[str, Any]] = asyncio.Future()
        self._pending_responses[echo] = future

        start_time = time.perf_counter()

        try:
            await self.ws.send(json.dumps(request))
            # 等待响应，超时 8 分钟
            response = await asyncio.wait_for(future, timeout=480.0)
            duration = time.perf_counter() - start_time

            # 检查响应状态
            status = response.get("status")
            if status == "failed":
                retcode = response.get("retcode", -1)
                msg = response.get("message", "未知错误")
                if suppress_error_retcodes and retcode in suppress_error_retcodes:
                    logger.warning(
                        f"[bold yellow][API预期失败][/bold yellow] [green]{action}[/green] (ID=[magenta]{echo}[/magenta]) | 耗时=[magenta]{duration:.2f}s[/magenta] | retcode=[yellow]{retcode}[/yellow] | message={msg}"
                    )
                else:
                    logger.error(
                        f"[bold red][API失败][/bold red] [green]{action}[/green] (ID=[magenta]{echo}[/magenta]) | 耗时=[magenta]{duration:.2f}s[/magenta] | retcode=[red]{retcode}[/red] | message={msg}"
                    )
                raise RuntimeError(f"API 调用失败: {msg} (retcode={retcode})")

            logger.info(
                f"[bold green][API成功][/bold green] [green]{action}[/green] (ID=[magenta]{echo}[/magenta]) | 耗时=[magenta]{duration:.2f}s[/magenta]"
            )
            if logger.isEnabledFor(logging.DEBUG):
                log_debug_json(logger, "[OneBot响应体]", response)
            return response
        except asyncio.TimeoutError:
            duration = time.perf_counter() - start_time
            logger.error(f"[API超时] {action} (ID={echo}) | 耗时={duration:.2f}s")
            raise
        finally:
            self._pending_responses.pop(echo, None)

    async def send_group_message(
        self,
        group_id: int,
        message: str | list[dict[str, Any]],
        *,
        mark_sent: bool = True,
    ) -> dict[str, Any]:
        """发送群消息"""
        result = await self._call_api(
            "send_group_msg",
            {
                "group_id": group_id,
                "message": message,
            },
        )
        if mark_sent:
            _mark_message_sent_this_turn()
        return result

    async def send_private_message(
        self,
        user_id: int,
        message: str | list[dict[str, Any]],
        *,
        mark_sent: bool = True,
    ) -> dict[str, Any]:
        """发送私聊消息"""
        result = await self._call_api(
            "send_private_msg",
            {
                "user_id": user_id,
                "message": message,
            },
        )
        if mark_sent:
            _mark_message_sent_this_turn()
        return result

    async def get_group_msg_history(
        self,
        group_id: int,
        message_seq: int | None = None,
        count: int = 500,
    ) -> list[dict[str, Any]]:
        """获取群消息历史

        参数:
            group_id: 群号
            message_seq: 起始消息序号，None 表示从最新消息开始
            count: 获取的消息数量

        返回:
            消息列表
        """
        params: dict[str, Any] = {
            "group_id": group_id,
            "count": count,
        }
        if message_seq is not None:
            params["message_seq"] = message_seq

        result = await self._call_api("get_group_msg_history", params)

        # 安全获取消息列表
        if result is None:
            logger.warning("get_group_msg_history 返回 None")
            return []

        data = result.get("data")
        if data is None:
            logger.warning(f"get_group_msg_history 响应无 data 字段: {result}")
            return []

        messages: list[dict[str, Any]] = data.get("messages", [])
        logger.debug(f"获取到 {len(messages)} 条历史消息")
        return messages

    async def get_image(self, file: str) -> str:
        """获取图片信息

        参数:
            file: 图片文件名或 URL

        返回:
            图片的本地路径或 URL
        """
        result = await self._call_api("get_image", {"file": file})
        data: dict[str, str] = result.get("data", {})
        url: str = data.get("url", "") or data.get("file", "")
        return url

    async def get_group_info(self, group_id: int) -> dict[str, Any] | None:
        """获取群信息

        参数:
            group_id: 群号

        返回:
            群信息字典，包含 group_name 等字段
        """
        try:
            result = await self._call_api("get_group_info", {"group_id": group_id})
            data: dict[str, Any] = result.get("data", {})
            return data
        except Exception as e:
            logger.error(f"获取群信息失败: {e}")
            return None

    async def get_stranger_info(self, user_id: int) -> dict[str, Any] | None:
        """获取陌生人信息

        参数:
            user_id: 用户QQ号

        返回:
            用户信息字典，包含 nickname 等字段
        """
        try:
            result = await self._call_api("get_stranger_info", {"user_id": user_id})
            data: dict[str, Any] = result.get("data", {})
            return data
        except Exception as e:
            logger.error(f"获取陌生人信息失败: {e}")
            return None

    async def get_group_member_info(
        self, group_id: int, user_id: int, no_cache: bool = False
    ) -> dict[str, Any] | None:
        """获取群成员信息

        参数:
            group_id: 群号
            user_id: 群成员QQ号
            no_cache: 是否不使用缓存（默认 false）

        返回:
            群成员信息字典，包含群昵称、QQ昵称、加群时间、等级、最后发言时间等字段
        """
        try:
            result = await self._call_api(
                "get_group_member_info",
                {"group_id": group_id, "user_id": user_id, "no_cache": no_cache},
            )
            data: dict[str, Any] = result.get("data", {})
            return data
        except Exception as e:
            logger.error(f"获取群成员信息失败: {e}")
            return None

    async def get_group_member_list(self, group_id: int) -> list[dict[str, Any]]:
        """获取群成员列表

        参数:
            group_id: 群号

        返回:
            群成员信息列表
        """
        try:
            result = await self._call_api(
                "get_group_member_list", {"group_id": group_id}
            )
            data: list[dict[str, Any]] = result.get("data", [])
            return data
        except Exception as e:
            logger.error(f"获取群成员列表失败: {e}")
            return []

    async def get_friend_list(self) -> list[dict[str, Any]]:
        """获取好友列表

        返回:
            好友信息列表，每个好友包含:
            - user_id: QQ号
            - nickname: QQ昵称
            - remark: 备注名
        """
        try:
            result = await self._call_api("get_friend_list")
            data: list[dict[str, Any]] = result.get("data", [])
            return data
        except Exception as e:
            logger.error(f"获取好友列表失败: {e}")
            return []

    async def get_group_list(self) -> list[dict[str, Any]]:
        """获取群列表

        返回:
            群信息列表，每个群包含:
            - group_id: 群号
            - group_name: 群名称
            - member_count: 成员数
            - max_member_count: 最大成员数
        """
        try:
            result = await self._call_api("get_group_list")
            data: list[dict[str, Any]] = result.get("data", [])
            return data
        except Exception as e:
            logger.error(f"获取群列表失败: {e}")
            return []

    async def get_forward_msg(self, id: str) -> list[dict[str, Any]]:
        """获取合并转发消息详情

        参数:
            id: 合并转发 ID

        返回:
            消息节点列表
        """
        try:
            result = await self._call_api(
                "get_forward_msg",
                {"message_id": id},
                suppress_error_retcodes={1200},
            )
            data = result.get("data", {})
            # data 可能是字典（包含 messages）或列表（直接是 nodes）
            if isinstance(data, dict):
                messages: list[dict[str, Any]] = data.get("messages", [])
                return messages
            elif isinstance(data, list):
                nodes: list[dict[str, Any]] = data
                return nodes
            return []
        except Exception as e:
            error_text = str(e)
            if "retcode=1200" in error_text:
                logger.debug(
                    "合并转发消息不可获取（可能过期或内层）: id=%s err=%s", id, e
                )
                return []
            logger.error(f"获取合并转发消息失败: {e}")
            return []

    async def get_msg(self, message_id: int) -> dict[str, Any] | None:
        """获取单条消息详情

        参数:
            message_id: 消息 ID

        返回:
            消息详情字典
        """
        try:
            result = await self._call_api("get_msg", {"message_id": message_id})
            return result.get("data")
        except Exception as e:
            logger.error(f"获取消息详情失败: {e}")
            return None

    async def send_forward_msg(
        self, group_id: int, messages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """发送合并转发消息到群聊

        参数:
            group_id: 群号
            messages: 消息节点列表，每个节点格式为:
                {
                    "type": "node",
                    "data": {
                        "name": "发送者昵称",
                        "uin": "发送者QQ号",
                        "content": "消息内容（字符串或消息段数组）",
                        "time": "时间戳（可选）"
                    }
                }

        返回:
            API 响应
        """
        return await self._call_api(
            "send_forward_msg", {"group_id": group_id, "messages": messages}
        )

    async def send_like(self, user_id: int, times: int = 1) -> dict[str, Any]:
        """给用户点赞

        参数:
            user_id: 对方 QQ 号
            times: 赞的次数（默认1次）

        返回:
            API 响应
        """
        return await self._call_api("send_like", {"user_id": user_id, "times": times})

    async def fetch_emoji_like(self, message_id: int) -> dict[str, Any]:
        """获取消息已设置的表情反应信息（扩展接口）。

        参数:
            message_id: 消息 ID

        返回:
            data 字段内容（字典），异常时抛出 RuntimeError
        """
        result = await self._call_api("fetch_emoji_like", {"message_id": message_id})
        data = result.get("data")
        if isinstance(data, dict):
            return data
        return {}

    async def set_msg_emoji_like(
        self,
        message_id: int,
        emoji_id: int,
        *,
        set_like: bool = True,
        mark_sent: bool = True,
    ) -> dict[str, Any]:
        """给指定消息添加/取消表情反应（扩展接口）。

        参数:
            message_id: 目标消息 ID
            emoji_id: 表情 ID
            set_like: True=添加反应，False=取消反应
            mark_sent: 是否标记本轮已发送（用于 end 工具判定）

        返回:
            API 响应
        """
        if set_like:
            try:
                result = await self._call_api(
                    "set_msg_emoji_like",
                    {"message_id": message_id, "emoji_id": emoji_id},
                )
            except RuntimeError:
                logger.warning(
                    "[消息表情] set_msg_emoji_like 默认参数失败，尝试 set=true 回退: msg=%s emoji=%s",
                    message_id,
                    emoji_id,
                )
                result = await self._call_api(
                    "set_msg_emoji_like",
                    {"message_id": message_id, "emoji_id": emoji_id, "set": True},
                )
        else:
            # 取消反应可能依赖实现方扩展参数，默认采用 set=false。
            result = await self._call_api(
                "set_msg_emoji_like",
                {"message_id": message_id, "emoji_id": emoji_id, "set": False},
            )

        if mark_sent:
            _mark_message_sent_this_turn()
        return result

    async def send_group_poke(
        self,
        group_id: int,
        user_id: int,
        *,
        mark_sent: bool = True,
    ) -> dict[str, Any]:
        """在群聊中拍一拍指定成员。

        参数:
            group_id: 群号
            user_id: 被拍一拍的用户 QQ 号
            mark_sent: 是否标记本轮已发送（用于 end 工具判定）

        返回:
            API 响应
        """
        try:
            result = await self._call_api(
                "group_poke", {"group_id": group_id, "user_id": user_id}
            )
        except RuntimeError:
            logger.warning(
                "[拍一拍] group_poke 失败，尝试 send_poke 回退: group=%s user=%s",
                group_id,
                user_id,
            )
            result = await self._call_api(
                "send_poke",
                {
                    "group_id": group_id,
                    "user_id": user_id,
                    "target_id": user_id,
                },
            )

        if mark_sent:
            _mark_message_sent_this_turn()
        return result

    async def send_private_poke(
        self,
        user_id: int,
        *,
        mark_sent: bool = True,
    ) -> dict[str, Any]:
        """在私聊中拍一拍指定用户。

        参数:
            user_id: 被拍一拍的用户 QQ 号
            mark_sent: 是否标记本轮已发送（用于 end 工具判定）

        返回:
            API 响应
        """
        try:
            result = await self._call_api("friend_poke", {"user_id": user_id})
        except RuntimeError:
            logger.warning(
                "[拍一拍] friend_poke 失败，尝试 send_poke 回退: user=%s",
                user_id,
            )
            result = await self._call_api(
                "send_poke",
                {
                    "user_id": user_id,
                    "target_id": user_id,
                },
            )

        if mark_sent:
            _mark_message_sent_this_turn()
        return result

    async def upload_group_file(
        self,
        group_id: int,
        file_path: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """上传文件到群聊

        参数:
            group_id: 群号
            file_path: 本地文件绝对路径
            name: 文件名（可选，默认使用原文件名）
        """
        from pathlib import Path as _Path

        file_name = name or _Path(file_path).name
        try:
            return await self._call_api(
                "upload_group_file",
                {
                    "group_id": group_id,
                    "file": file_path,
                    "name": file_name,
                },
            )
        except RuntimeError:
            # 回退：尝试用文件消息段发送
            logger.warning(
                "[文件上传] upload_group_file 失败，尝试文件消息段回退: group=%s",
                group_id,
            )
            return await self.send_group_message(
                group_id,
                [
                    {
                        "type": "file",
                        "data": {"file": f"file://{file_path}", "name": file_name},
                    }
                ],
            )

    async def upload_private_file(
        self,
        user_id: int,
        file_path: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """上传文件到私聊

        参数:
            user_id: 用户 QQ 号
            file_path: 本地文件绝对路径
            name: 文件名（可选，默认使用原文件名）
        """
        from pathlib import Path as _Path

        file_name = name or _Path(file_path).name
        try:
            return await self._call_api(
                "upload_private_file",
                {
                    "user_id": user_id,
                    "file": file_path,
                    "name": file_name,
                },
            )
        except RuntimeError:
            logger.warning(
                "[文件上传] upload_private_file 失败，尝试文件消息段回退: user=%s",
                user_id,
            )
            return await self.send_private_message(
                user_id,
                [
                    {
                        "type": "file",
                        "data": {"file": f"file://{file_path}", "name": file_name},
                    }
                ],
            )

    async def send_group_sign(self, group_id: int) -> dict[str, Any]:
        """执行群打卡

        参数:
            group_id: 群号

        返回:
            API 响应
        """
        return await self._call_api("send_group_sign", {"group_id": group_id})

    async def _get_group_notices(self, group_id: int) -> list[dict[str, Any]]:
        """获取群公告列表（非标准 API，依赖具体实现）

        参数:
            group_id: 群号

        返回:
            公告列表
        """
        try:
            result = await self._call_api("_get_group_notice", {"group_id": group_id})
            data = result.get("data")
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                # 尝试获取常见的列表字段
                notices = data.get("notices")
                if notices is None:
                    notices = data.get("list")
                if isinstance(notices, list):
                    return notices
            return []
        except Exception as e:
            logger.error(f"获取群公告失败: {e}")
            return []

    async def run(self) -> None:
        """运行消息接收循环"""
        if not self.ws:
            raise RuntimeError("WebSocket 未连接")

        self._running = True
        self._tasks: set[asyncio.Task[None]] = set()
        logger.info("[WebSocket] 消息接收循环已启动")

        try:
            while self._running:
                raw_message = ""
                try:
                    message_data = await self.ws.recv()
                    raw_message = (
                        message_data.decode("utf-8")
                        if isinstance(message_data, bytes)
                        else message_data
                    )
                    data = json.loads(raw_message)
                    # 处理消息（不阻塞接收循环）
                    await self._dispatch_message(data)
                except json.JSONDecodeError as e:
                    logger.error(
                        f"[WebSocket] 无法解析 JSON 消息: {raw_message!r}, 错误: {e}"
                    )
                except websockets.ConnectionClosed:
                    logger.warning("[WebSocket] 连接已关闭，接收循环结束")
                    break
                except Exception as e:
                    logger.exception(f"[WebSocket] 接收消息时发生异常: {e}")
        finally:
            self._running = False
            # 等待所有后台任务完成
            if self._tasks:
                logger.debug(
                    f"[WebSocket] 正在等待 {len(self._tasks)} 个异步任务完成..."
                )
                await asyncio.gather(*self._tasks, return_exceptions=True)
            logger.info("[WebSocket] 接收循环已停止")

    async def _dispatch_message(self, data: dict[str, Any]) -> None:
        """分发消息（API响应同步处理，事件异步处理）"""
        if logger.isEnabledFor(logging.DEBUG):
            log_debug_json(logger, "[WebSocket消息]", data)
        # 检查是否是 API 响应（需要立即处理）
        echo = data.get("echo")
        if echo is not None:
            echo_str = str(echo)
            if echo_str in self._pending_responses:
                logger.debug(f"收到 API 响应: echo={echo_str}")
                self._pending_responses[echo_str].set_result(data)
                return
            else:
                logger.debug(
                    f"收到未知 echo 响应: {echo_str}, 待处理: {list(self._pending_responses.keys())}"
                )
                return

        # 事件类型的消息异步处理，不阻塞接收循环
        post_type = data.get("post_type")
        if post_type == "message":
            msg_type = data.get("message_type", "unknown")
            sender = data.get("sender", {}).get("user_id", "unknown")
            logger.info(
                f"[bold blue][收到消息][/bold blue] type=[yellow]{msg_type}[/yellow], sender=[blue]{sender}[/blue]"
            )
            if self._message_handler:
                # 创建后台任务处理消息
                task = asyncio.create_task(self._safe_handle_message(data))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        elif post_type == "notice":
            notice_type = data.get("notice_type", "")
            sub_type = data.get("sub_type", "")
            # 处理拍一拍事件
            if notice_type == "notify" and sub_type == "poke":
                target_id = data.get("target_id", 0)
                sender_id = data.get("user_id", 0)
                group_id = data.get("group_id", 0)
                logger.info(
                    f"[bold magenta][收到拍一拍][/bold magenta] sender=[blue]{sender_id}[/blue], target=[blue]{target_id}[/blue], group=[blue]{group_id}[/blue]"
                )
                if self._message_handler:
                    # 将 poke 事件转换为类似消息的格式，方便 handler 处理
                    poke_event = {
                        "post_type": "notice",
                        "notice_type": "poke",
                        "group_id": group_id,
                        "user_id": sender_id,
                        "sender": {"user_id": sender_id},
                        "target_id": target_id,
                        "message": [],  # 空消息
                    }
                    task = asyncio.create_task(self._safe_handle_message(poke_event))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
            else:
                logger.debug(
                    f"收到通知事件: notice_type={notice_type}, sub_type={sub_type}"
                )
        elif post_type:
            logger.debug(
                f"收到事件: post_type={post_type}, meta={data.get('meta_event_type', '')}"
            )

    async def _safe_handle_message(self, data: dict[str, Any]) -> None:
        """安全地处理消息（捕获异常）"""
        try:
            if self._message_handler:
                await self._message_handler(data)
        except Exception as e:
            logger.exception(f"处理消息时出错: {e}")

    async def run_with_reconnect(self, reconnect_interval: float = 5.0) -> None:
        """带自动重连的运行"""
        self._should_stop = False
        reconnect_count = 0

        while not self._should_stop:
            try:
                if reconnect_count > 0:
                    logger.info(f"[WebSocket] 正在尝试第 {reconnect_count} 次重连...")
                await self.connect()
                reconnect_count = 0  # 连接成功重置计数
                await self.run()
            except websockets.ConnectionClosed as e:
                logger.warning(f"[WebSocket] 连接已断开: {e}")
            except Exception as e:
                logger.error(f"[WebSocket] 发生错误: {e}")

            if self._should_stop:
                break

            reconnect_count += 1
            logger.info(f"{reconnect_interval} 秒后尝试重连...")
            await asyncio.sleep(reconnect_interval)

    def stop(self) -> None:
        """停止运行"""
        self._should_stop = True
        self._running = False


def parse_message_time(message: dict[str, Any]) -> datetime:
    """解析消息时间。

    兼容秒级/毫秒级时间戳与字符串输入，异常时回退到当前时间。
    """

    raw_timestamp = message.get("time")

    if raw_timestamp is None:
        return datetime.now()

    try:
        timestamp = float(raw_timestamp)
    except (TypeError, ValueError):
        logger.debug("[OneBot] 无法解析消息时间戳，使用当前时间: %s", raw_timestamp)
        return datetime.now()

    # 13 位毫秒时间戳自动降为秒。
    if timestamp > 1_000_000_000_000:
        timestamp /= 1000.0

    if timestamp <= 0:
        return datetime.now()

    try:
        return datetime.fromtimestamp(timestamp)
    except (OSError, OverflowError, ValueError):
        logger.debug("[OneBot] 时间戳越界，使用当前时间: %s", raw_timestamp)
        return datetime.now()


def get_message_sender_id(message: dict[str, Any]) -> int:
    """获取消息发送者 QQ 号"""
    sender: dict[str, Any] = message.get("sender", {})
    user_id: int = sender.get("user_id", 0)
    return user_id


def get_message_content(message: dict[str, Any]) -> list[dict[str, Any]]:
    """获取消息内容（CQ 码数组格式）"""
    msg = message.get("message", [])
    if isinstance(msg, str):
        # 如果是字符串格式，转换为数组格式
        return [{"type": "text", "data": {"text": msg}}]
    content: list[dict[str, Any]] = msg
    return content
