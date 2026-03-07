from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from Undefined.skills.tools.python_interpreter import handler as python_handler


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

    async def _fake_create_subprocess_exec(
        *args: str, **kwargs: object
    ) -> _FakeProcess:
        calls.append(tuple(args))
        return _FakeProcess()

    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        _fake_create_subprocess_exec,
    )

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

    assert "--network" in exec_cmd
    assert "none" in exec_cmd
    assert "--read-only" in exec_cmd
    assert "PYTHONPATH=/tmp/_site_packages" in exec_cmd
    assert "python /tmp/_script.py" in " ".join(exec_cmd)
