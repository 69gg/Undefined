import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import secrets
from typing import Any
from Undefined.config.webui_settings import DEFAULT_WEBUI_STOP_TIMEOUT_SECONDS
from Undefined.utils.io import run_cancellation_safe, write_json_sync

logger = logging.getLogger(__name__)

#: 登录态有效期。控制台属于本地自托管面板，长有效期配合活跃滑动续期，
#: 让长期使用的浏览器不必反复登录。
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
ACCESS_TOKEN_TTL_SECONDS = 15 * 60
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
SESSION_FILE_VERSION = 1


def _password_fingerprint(password: str | None) -> str | None:
    """会话文件只保存密码指纹，用于在密码变更后作废旧登录态。"""
    if password is None:
        return None
    return hashlib.sha256(password.encode("utf-8")).hexdigest()[:16]


#: 拉起 Bot 子进程的命令。
#:
#: 用**当前解释器**直接跑模块，而不是 ``uv run``：WebUI 自己就跑在这个解释器里，
#: 它必然能 import 到本包；``uv run`` 则要求环境里存在 uv，并会按
#: pyproject/uv.lock 尝试同步环境——本体镜像的 runtime 阶段是从
#: ``python:3.12-slim-bookworm`` 重新开始的，只带了 ``/opt/venv``（见
#: ``src/Undefined/deploy/templates/Dockerfile.bot``），里面没有 uv，
#: 于是容器内点「启动机器人」只会 FileNotFoundError。
BOT_COMMAND = (sys.executable, "-m", "Undefined")


@dataclass
class SessionEntry:
    expires_at: float
    kind: str = "session"


class SessionStore:
    """WebUI 会话表。

    传入 ``storage_path`` 时会话会原子写入磁盘，控制台重启后自动恢复，
    浏览器手里的 cookie / 令牌无需重新登录即可继续使用。
    """

    def __init__(
        self,
        ttl_seconds: int = SESSION_TTL_SECONDS,
        access_ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS,
        refresh_ttl_seconds: int = REFRESH_TOKEN_TTL_SECONDS,
        storage_path: Path | None = None,
        password: str | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._access_ttl_seconds = access_ttl_seconds
        self._refresh_ttl_seconds = refresh_ttl_seconds
        self._storage_path = storage_path
        self._password_fingerprint = _password_fingerprint(password)
        self._sessions: dict[str, SessionEntry] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        path = self._storage_path
        if path is None:
            return
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except (OSError, UnicodeError) as exc:
            logger.warning("[WebUI] 读取会话文件失败: %s", exc)
            return
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning("[WebUI] 会话文件损坏，已忽略: %s", path)
            return
        if not isinstance(payload, dict):
            return
        stored_fingerprint = payload.get("password_fingerprint")
        if (
            self._password_fingerprint is not None
            and stored_fingerprint != self._password_fingerprint
        ):
            # 密码已变更（例如直接编辑 config.toml 后重启），旧令牌必须失效。
            logger.info("[WebUI] 管理密码已变更，清除旧登录会话")
            # 立即用新指纹覆盖磁盘，避免密码回滚后旧会话重新生效。
            self._persist()
            return
        raw_sessions = payload.get("sessions")
        if not isinstance(raw_sessions, dict):
            return
        now = time.time()
        for token, value in raw_sessions.items():
            if not isinstance(token, str) or not token or not isinstance(value, dict):
                continue
            try:
                expires_at = float(value.get("expires_at") or 0)
            except (TypeError, ValueError):
                continue
            kind = str(value.get("kind") or "session")
            if kind not in {"session", "access", "refresh"} or expires_at <= now:
                continue
            self._sessions[token] = SessionEntry(expires_at=expires_at, kind=kind)

    def _payload(self) -> dict[str, object]:
        now = time.time()
        return {
            "version": SESSION_FILE_VERSION,
            "password_fingerprint": self._password_fingerprint,
            "sessions": {
                token: {"expires_at": entry.expires_at, "kind": entry.kind}
                for token, entry in self._sessions.items()
                if entry.expires_at > now
            },
        }

    def _persist_strict(self) -> None:
        """写盘失败时向上抛出，供登出/刷新等需要强一致性的路径回滚。"""
        path = self._storage_path
        if path is None:
            return
        write_json_sync(path, self._payload(), use_lock=False)

    def _prune_expired(self) -> None:
        now = time.time()
        for token in [
            token for token, entry in self._sessions.items() if entry.expires_at <= now
        ]:
            self._sessions.pop(token, None)

    def _persist(self) -> None:
        """登录与校验路径的 best-effort 写盘；磁盘异常只告警。"""
        try:
            self._persist_strict()
        except Exception as exc:  # 磁盘异常不应让登录/校验直接失败
            logger.warning("[WebUI] 写入会话文件失败: %s", exc)
            return
        self._prune_expired()

    def create(self, *, ttl_seconds: int | None = None, kind: str = "session") -> str:
        token = secrets.token_urlsafe(32)
        ttl = self._ttl_seconds if ttl_seconds is None else ttl_seconds
        with self._lock:
            self._sessions[token] = SessionEntry(
                expires_at=time.time() + ttl, kind=kind
            )
            self._persist()
        return token

    def _resolve_entry(self, token: str | None) -> SessionEntry | None:
        if not token:
            return None
        with self._lock:
            entry = self._sessions.get(token)
            if entry is None:
                return None
            now = time.time()
            if entry.expires_at < now:
                self._sessions.pop(token, None)
                self._persist()
                return None
            # 活跃会话滑动续期：剩余不足一半时重新计时，长期使用不会掉线。
            if entry.kind == "session":
                ttl = self._ttl_seconds
                if ttl > 0 and entry.expires_at - now < ttl / 2:
                    entry.expires_at = now + ttl
                    self._persist()
            return entry

    def is_valid(
        self,
        token: str | None,
        *,
        allowed_kinds: set[str] | None = None,
    ) -> bool:
        entry = self._resolve_entry(token)
        if entry is None:
            return False
        if allowed_kinds is not None and entry.kind not in allowed_kinds:
            return False
        return True

    def get_expiry_ms(self, token: str | None) -> int:
        entry = self._resolve_entry(token)
        if entry is None:
            return 0
        return int(entry.expires_at * 1000)

    def get_kind(self, token: str | None) -> str | None:
        entry = self._resolve_entry(token)
        return None if entry is None else entry.kind

    def _issue_auth_tokens_locked(self) -> dict[str, int | str]:
        now = time.time()
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        self._sessions[access_token] = SessionEntry(
            expires_at=now + self._access_ttl_seconds, kind="access"
        )
        self._sessions[refresh_token] = SessionEntry(
            expires_at=now + self._refresh_ttl_seconds, kind="refresh"
        )
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": self._access_ttl_seconds,
            "refresh_expires_in": self._refresh_ttl_seconds,
            "access_token_expires_at": int((now + self._access_ttl_seconds) * 1000),
        }

    def issue_auth_tokens(self) -> dict[str, int | str]:
        with self._lock:
            tokens = self._issue_auth_tokens_locked()
            self._persist()
            return tokens

    def refresh_auth_tokens(
        self, refresh_token: str | None
    ) -> dict[str, int | str] | None:
        if not refresh_token:
            return None
        with self._lock:
            entry = self._sessions.get(refresh_token)
            if entry is None or entry.kind != "refresh":
                return None
            if entry.expires_at < time.time():
                self._sessions.pop(refresh_token, None)
                try:
                    self._persist_strict()
                except Exception:
                    self._sessions[refresh_token] = entry
                    raise
                return None
            # 旧 refresh token 立即作废并轮换，避免重放。
            previous = dict(self._sessions)
            self._sessions.pop(refresh_token, None)
            tokens = self._issue_auth_tokens_locked()
            try:
                self._persist_strict()
            except Exception:
                self._sessions = previous
                raise
            return tokens

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            entry = self._sessions.pop(token, None)
            if entry is None:
                return
            try:
                self._persist_strict()
            except Exception:
                self._sessions[token] = entry
                raise

    def set_password(self, password: str | None) -> None:
        """密码变更后作废全部旧会话，并更新会话文件中的密码指纹。"""
        with self._lock:
            previous_fingerprint = self._password_fingerprint
            previous = dict(self._sessions)
            self._password_fingerprint = _password_fingerprint(password)
            self._sessions.clear()
            try:
                self._persist_strict()
            except Exception:
                self._password_fingerprint = previous_fingerprint
                self._sessions = previous
                raise

    def clear(self) -> None:
        with self._lock:
            previous = dict(self._sessions)
            self._sessions.clear()
            try:
                self._persist_strict()
            except Exception:
                self._sessions = previous
                raise


class BotProcessController:
    def __init__(
        self, *, stop_timeout_getter: Callable[[], float] | None = None
    ) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._started_at: float | None = None
        self._lock = asyncio.Lock()
        self._watch_task: asyncio.Task[None] | None = None
        self._is_windows = os.name == "nt"
        self._start_new_session = not self._is_windows
        self._creationflags = 0
        self._ctrl_break_signal: int | None = None
        self._stop_timeout_getter = stop_timeout_getter or (
            lambda: DEFAULT_WEBUI_STOP_TIMEOUT_SECONDS
        )
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
        # 客户端断开/重复取消不能留下未收敛的子进程或提前释放生命周期锁。
        return await run_cancellation_safe(self._stop())

    async def _stop(self) -> dict[str, Any]:
        watch_task: asyncio.Task[None] | None = None
        async with self._lock:
            if not self._process or self._process.returncode is not None:
                self._process = None
                self._started_at = None
                return self.status()
            logger.info("[WebUI] 停止机器人进程: pid=%s", self._process.pid)
            process = self._process
            stop_timeout = self._stop_timeout_getter()
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
                    await asyncio.wait_for(
                        process.wait(),
                        timeout=stop_timeout if stop_timeout > 0 else None,
                    )
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
                if process.returncode is not None:
                    watch_task = self._watch_task
                    self._watch_task = None
                    self._process = None
                    self._started_at = None

        # watcher 的 finally 也会取得 _lock，必须在释放锁后等待。
        if watch_task is not None:
            if not watch_task.done():
                watch_task.cancel()
            try:
                await watch_task
            except asyncio.CancelledError:
                pass
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
