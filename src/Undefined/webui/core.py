import asyncio
import logging
import os
import signal
import subprocess
import time
import secrets
from typing import Any

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 8 * 60 * 60
BOT_COMMAND = ("uv", "run", "Undefined")


class SessionStore:
    def __init__(self, ttl_seconds: int = SESSION_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, float] = {}

    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = time.time() + self._ttl_seconds
        return token

    def is_valid(self, token: str | None) -> bool:
        if not token:
            return False
        expiry = self._sessions.get(token)
        if not expiry:
            return False
        if expiry < time.time():
            self._sessions.pop(token, None)
            return False
        return True

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        self._sessions.pop(token, None)


class BotProcessController:
    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._started_at: float | None = None
        self._lock = asyncio.Lock()
        self._watch_task: asyncio.Task[None] | None = None
        self._is_windows = os.name == "nt"
        self._start_new_session = not self._is_windows
        self._creationflags = 0
        self._ctrl_break_signal: int | None = None
        if self._is_windows:
            self._creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            self._ctrl_break_signal = getattr(signal, "CTRL_BREAK_EVENT", None)

    def status(self) -> dict[str, Any]:
        running = bool(self._process and self._process.returncode is None)
        uptime = 0.0
        if running and self._started_at:
            uptime = max(0.0, time.time() - self._started_at)
        return {
            "running": running,
            "pid": self._process.pid if running and self._process else None,
            "started_at": self._started_at,
            "uptime_seconds": uptime,
            "command": " ".join(BOT_COMMAND),
        }

    async def start(self) -> dict[str, Any]:
        async with self._lock:
            if self._process and self._process.returncode is None:
                return self.status()
            logger.info("[WebUI] 启动机器人进程: %s", " ".join(BOT_COMMAND))
            if self._start_new_session:
                logger.info("[WebUI] 机器人进程已启用独立进程组")
            elif self._creationflags:
                logger.info("[WebUI] 机器人进程已启用 Windows 进程组")

            # 传递环境变量，强制根据配置开启颜色
            env = os.environ.copy()
            # 许多工具检测到非 TTY 会禁用颜色，这里强制开启
            env["FORCE_COLOR"] = "1"
            env["CLICOLOR_FORCE"] = "1"
            env["PYTHONUNBUFFERED"] = "1"

            try:
                kwargs: dict[str, Any] = {}
                if self._start_new_session:
                    kwargs["start_new_session"] = True
                elif self._creationflags:
                    kwargs["creationflags"] = self._creationflags

                self._process = await asyncio.create_subprocess_exec(
                    *BOT_COMMAND,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=env,
                    **kwargs,
                )
                self._started_at = time.time()
                self._watch_task = asyncio.create_task(
                    self._watch_process(self._process)
                )
            except Exception as e:
                logger.error(f"启动失败: {e}")

            return self.status()

    async def stop(self) -> dict[str, Any]:
        async with self._lock:
            if not self._process or self._process.returncode is not None:
                self._process = None
                self._started_at = None
                return self.status()
            logger.info("[WebUI] 停止机器人进程: pid=%s", self._process.pid)
            process = self._process
            try:
                if self._start_new_session and process.pid:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                elif self._is_windows and self._creationflags and process.pid:
                    if self._ctrl_break_signal is not None:
                        try:
                            process.send_signal(self._ctrl_break_signal)
                        except (ProcessLookupError, ValueError, AttributeError):
                            process.terminate()
                    else:
                        process.terminate()
                else:
                    process.terminate()

                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    logger.warning("[WebUI] 机器人进程未及时退出，强制终止")
                    if self._start_new_session and process.pid:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    else:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2)
                    except asyncio.TimeoutError:
                        logger.warning("[WebUI] 机器人进程终止超时，跳过等待")
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.error(f"停止进程出错: {e}")
            finally:
                if self._watch_task and not self._watch_task.done():
                    self._watch_task.cancel()
                    try:
                        await self._watch_task
                    except asyncio.CancelledError:
                        pass
                self._watch_task = None
                self._process = None
                self._started_at = None

            return self.status()

    async def _watch_process(self, process: asyncio.subprocess.Process) -> None:
        try:
            await process.wait()
        except Exception:
            pass
        finally:
            async with self._lock:
                if self._process is process:
                    self._process = None
                    self._started_at = None
