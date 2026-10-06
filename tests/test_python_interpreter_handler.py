from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from Undefined.skills.tools.python_interpreter import handler as python_handler


@pytest.fixture(autouse=True)
def clear_shared_directory_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(python_handler.SHARED_LOCAL_DIR_ENV, raising=False)
    monkeypatch.delenv(python_handler.SHARED_HOST_DIR_ENV, raising=False)


class _FakeProcess:
    def __init__(self, *, returncode: int = 0) -> None:
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""

    def terminate(self) -> None:
        return None

    async def wait(self) -> int:
        return self.returncode


def test_resolve_output_host_path_rejects_symlink_escape(tmp_path: Path) -> None:
    host_tmpdir = tmp_path / "mounted"
    host_tmpdir.mkdir()
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")
    (host_tmpdir / "leak.txt").symlink_to(outside_file)

    assert (
        python_handler._resolve_output_host_path(
            "/tmp/leak.txt",
            str(host_tmpdir),
        )
        is None
    )


@pytest.mark.asyncio
async def test_execute_rejects_send_files_that_escape_tmp_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unexpected_subprocess(*args: object, **kwargs: object) -> None:
        raise AssertionError("subprocess should not be called")

    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        _unexpected_subprocess,
    )

    result = await python_handler.execute(
        {
            "code": "print('hello')",
            "send_files": ["/tmp/../../data0/Undefined/config.toml"],
        },
        {},
    )

    assert "错误: 输出文件路径必须位于容器 /tmp 目录内" in result


@pytest.mark.asyncio
async def test_execute_with_libraries_runs_user_code_in_network_isolated_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    script_paths: list[str] = []

    async def _fake_create_subprocess_exec(
        *args: str, **kwargs: object
    ) -> _FakeProcess:
        calls.append(tuple(args))
        source = Path(args[args.index("-v") + 1].removesuffix(":/tmp"))
        assert source.is_dir()
        if len(calls) == 1:
            assert (source / "_requirements.txt").read_text() == "requests\n"
            assert not (source / "_script.py").exists()
        else:
            assert (source / "_script.py").read_text() == "print('hello')"
        return _FakeProcess()

    real_mkdtemp = tempfile.mkdtemp

    def _tracked_mkdtemp(prefix: str) -> str:
        path = real_mkdtemp(prefix=prefix)
        script_paths.append(str(Path(path) / "_script.py"))
        return path

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
    monkeypatch.setattr(tempfile, "mkdtemp", _tracked_mkdtemp)

    result = await python_handler.execute(
        {
            "code": "print('hello')",
            "libraries": ["requests"],
        },
        {},
    )

    assert result == "代码执行成功 (无输出)。"
    assert len(calls) == 2

    install_cmd = calls[0]
    exec_cmd = calls[1]

    assert "--network" not in install_cmd
    assert "python /tmp/_script.py" not in " ".join(install_cmd)
    assert "pip install" in " ".join(install_cmd)
    assert "--user" in install_cmd
    assert f"{os.getuid()}:{os.getgid()}" in install_cmd
    assert len(script_paths) == 1
    assert not Path(script_paths[0]).exists()

    assert "--network" in exec_cmd
    assert "none" in exec_cmd
    assert "--read-only" in exec_cmd
    assert "PYTHONPATH=/tmp/_site_packages" in exec_cmd
    assert "python /tmp/_script.py" in " ".join(exec_cmd)
    assert "--user" in exec_cmd
    assert f"{os.getuid()}:{os.getgid()}" in exec_cmd


@pytest.mark.asyncio
async def test_execute_defers_cleanup_after_sending_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host_tmpdir = tmp_path / "mounted"
    host_tmpdir.mkdir()
    output_file = host_tmpdir / "result.txt"
    output_file.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix: str(host_tmpdir))
    monkeypatch.setattr(
        python_handler,
        "_run_docker_command",
        AsyncMock(return_value=(0, "", "")),
    )
    send_files_mock = AsyncMock(return_value="已发送: result.txt")
    monkeypatch.setattr(python_handler, "_send_output_files", send_files_mock)
    cleanup_mock = MagicMock()
    monkeypatch.setattr(python_handler, "_schedule_output_dir_cleanup", cleanup_mock)

    result = await python_handler.execute(
        {
            "code": "print('hello')",
            "send_files": ["/tmp/result.txt"],
        },
        {},
    )

    assert result == "代码执行成功 (无输出)。\n已发送: result.txt"
    cleanup_mock.assert_called_once_with(str(host_tmpdir))
    assert output_file.exists()


@pytest.mark.asyncio
async def test_cleanup_output_dir_later_removes_directory(tmp_path: Path) -> None:
    host_tmpdir = tmp_path / "mounted"
    host_tmpdir.mkdir()
    (host_tmpdir / "result.txt").write_text("hello", encoding="utf-8")

    await python_handler._cleanup_output_dir_later(str(host_tmpdir), 0)

    assert not host_tmpdir.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_libraries", (False, True))
async def test_shared_directory_uses_daemon_path_and_reads_outputs_locally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_libraries: bool
) -> None:
    # 两个名字模拟 bind mount 两端：Bot 和宿主 daemon 路径不同，底层目录相同。
    host_root = tmp_path / "daemon" / "shared"
    host_root.mkdir(parents=True)
    local_root = tmp_path / "bot" / "shared"
    local_root.parent.mkdir()
    local_root.symlink_to(host_root, target_is_directory=True)
    monkeypatch.setenv(python_handler.SHARED_LOCAL_DIR_ENV, str(local_root))
    monkeypatch.setenv(python_handler.SHARED_HOST_DIR_ENV, str(host_root))
    mounts: list[Path] = []
    cleanup_paths: list[str] = []

    async def run_docker(cmd: list[str], *, timeout: float) -> tuple[int, str, str]:
        source = Path(cmd[cmd.index("-v") + 1].removesuffix(":/tmp"))
        mounts.append(source)
        assert source.parent == host_root
        if "--network" not in cmd:
            assert (source / "_requirements.txt").read_text() == "requests\n"
            assert not (source / "_script.py").exists()
            return 0, "", ""
        assert (source / "_script.py").read_text() == "print('shared')"
        (source / "result.txt").write_text("shared output", encoding="utf-8")
        return 0, "shared\n", ""

    async def send_outputs(
        files: list[str], execution_dir: str, context: dict[str, Any]
    ) -> str:
        assert Path(execution_dir).parent == local_root
        output = python_handler._resolve_output_host_path(files[0], execution_dir)
        assert output is not None
        assert output.read_text() == "shared output"
        return "已发送: result.txt"

    monkeypatch.setattr(python_handler, "_run_docker_command", run_docker)
    monkeypatch.setattr(python_handler, "_send_output_files", send_outputs)
    monkeypatch.setattr(
        python_handler, "_schedule_output_dir_cleanup", cleanup_paths.append
    )

    result = await python_handler.execute(
        {
            "code": "print('shared')",
            "libraries": ["requests"] if with_libraries else [],
            "send_files": ["/tmp/result.txt"],
        },
        {},
    )

    assert result == "shared\n\n已发送: result.txt"
    assert len(mounts) == (2 if with_libraries else 1)
    assert len(set(mounts)) == 1
    assert len(cleanup_paths) == 1
    await python_handler._cleanup_output_dir_later(cleanup_paths[0], 0)
    assert not mounts[0].exists()


@pytest.mark.parametrize("missing", ("local", "host"))
def test_shared_directory_requires_both_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    name = (
        python_handler.SHARED_HOST_DIR_ENV
        if missing == "local"
        else python_handler.SHARED_LOCAL_DIR_ENV
    )
    monkeypatch.setenv(name, str(tmp_path / "shared"))

    with pytest.raises(ValueError, match="必须同时配置"):
        python_handler._create_execution_dirs()
    assert not (tmp_path / "shared").exists()
