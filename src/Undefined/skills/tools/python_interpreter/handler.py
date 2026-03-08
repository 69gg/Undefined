import asyncio
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Docker 执行配置
DOCKER_IMAGE = "python:3.11-slim"
DOCKER_USER = "65534:65534"
MEMORY_LIMIT = "128m"
MEMORY_LIMIT_WITH_LIBS = "512m"
CPU_LIMIT = "0.5"
TIMEOUT = 480  # 8 分钟
TIMEOUT_WITH_LIBS = 600  # 10 分钟（pip 安装需要更多时间）
OUTPUT_FILE_RETENTION_SECONDS = 30.0

# 图片扩展名（内联发送而非文件附件）
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"})

# 安全：库名仅允许 PyPI 合法字符，必须以字母/数字开头（防止 -r/-e/--index-url 注入）
_SAFE_LIB_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-\[\],<>=!~]*$")
_PENDING_CLEANUP_TASKS: set[asyncio.Task[None]] = set()


def _get_output_relative_path(container_path: str) -> PurePosixPath | None:
    try:
        relative = PurePosixPath(container_path).relative_to("/tmp")
    except (TypeError, ValueError):
        return None
    return relative if relative.parts else None


def _resolve_output_host_path(container_path: str, host_tmpdir: str) -> Path | None:
    """将容器内 /tmp 路径映射到宿主机临时目录，并拒绝目录穿越/符号链接逃逸。"""
    relative = _get_output_relative_path(container_path)
    if relative is None:
        return None

    host_tmp_root = Path(host_tmpdir).resolve()
    candidate = (host_tmp_root / relative.as_posix()).resolve(strict=False)

    try:
        candidate.relative_to(host_tmp_root)
    except ValueError:
        return None

    return candidate


async def _cleanup_output_dir_later(host_tmpdir: str, delay_seconds: float) -> None:
    try:
        await asyncio.sleep(delay_seconds)
        await asyncio.to_thread(shutil.rmtree, host_tmpdir, True)
    finally:
        task = asyncio.current_task()
        if task is not None:
            _PENDING_CLEANUP_TASKS.discard(task)


def _schedule_output_dir_cleanup(host_tmpdir: str) -> None:
    task = asyncio.create_task(
        _cleanup_output_dir_later(host_tmpdir, OUTPUT_FILE_RETENTION_SECONDS)
    )
    _PENDING_CLEANUP_TASKS.add(task)


def _build_docker_base_cmd(host_tmpdir: str, memory: str) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--memory",
        memory,
        "--cpus",
        CPU_LIMIT,
        "--user",
        DOCKER_USER,
        "-v",
        f"{host_tmpdir}:/tmp",
    ]


def _build_install_cmd(host_tmpdir: str, memory: str) -> list[str]:
    cmd = _build_docker_base_cmd(host_tmpdir, memory)
    cmd.append(DOCKER_IMAGE)
    cmd.extend(
        [
            "sh",
            "-c",
            "python -m pip install --quiet --disable-pip-version-check "
            "--no-cache-dir -r /tmp/_requirements.txt --target /tmp/_site_packages; "
            "_e=$?; chmod -R a+rw /tmp 2>/dev/null; exit $_e",
        ]
    )
    return cmd


def _build_exec_cmd(
    host_tmpdir: str,
    memory: str,
    *,
    pythonpath: str | None = None,
) -> list[str]:
    cmd = _build_docker_base_cmd(host_tmpdir, memory)
    cmd.extend(["--network", "none", "--read-only"])
    if pythonpath:
        cmd.extend(["-e", f"PYTHONPATH={pythonpath}"])
    cmd.append(DOCKER_IMAGE)
    cmd.extend(
        [
            "sh",
            "-c",
            "python /tmp/_script.py; _e=$?; chmod -R a+rw /tmp 2>/dev/null; exit $_e",
        ]
    )
    return cmd


async def _run_docker_command(
    cmd: list[str],
    *,
    timeout: float,
) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        try:
            process.terminate()
            await process.wait()
        except Exception as e:
            logger.error("[Python解释器] 终止超时进程失败: %s", e)
        raise

    return (
        process.returncode if process.returncode is not None else 1,
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
    )


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """在 Docker 容器中执行 Python 代码，可选安装库和发送输出文件。"""
    code = args.get("code", "")
    if not code:
        return "错误: 未提供代码。"

    libraries: list[str] = args.get("libraries") or []
    send_files: list[str] = args.get("send_files") or []

    # 验证库名
    for lib in libraries:
        if not _SAFE_LIB_PATTERN.match(lib):
            return f"错误: 无效的库名 '{lib}'。"

    has_libs = bool(libraries)
    memory = MEMORY_LIMIT_WITH_LIBS if has_libs else MEMORY_LIMIT
    timeout = TIMEOUT_WITH_LIBS if has_libs else TIMEOUT

    # 创建宿主机临时目录，绑定挂载到容器 /tmp
    host_tmpdir = tempfile.mkdtemp(prefix="pyinterp_")
    defer_cleanup = False

    try:
        # 验证文件路径必须绑定到容器 /tmp，并且不能逃逸宿主机临时目录
        for fpath in send_files:
            if _resolve_output_host_path(fpath, host_tmpdir) is None:
                return f"错误: 输出文件路径必须位于容器 /tmp 目录内: '{fpath}'"

        script_path = os.path.join(host_tmpdir, "_script.py")
        deadline = time.monotonic() + timeout

        if has_libs:
            # 单独安装依赖，再以无网络/只读根文件系统执行用户代码。
            req_path = os.path.join(host_tmpdir, "_requirements.txt")
            with open(req_path, "w", encoding="utf-8") as f:
                for lib in libraries:
                    f.write(lib + "\n")
            install_timeout = max(deadline - time.monotonic(), 1.0)
            install_cmd = _build_install_cmd(host_tmpdir, memory)
            install_code, install_stdout, install_stderr = await _run_docker_command(
                install_cmd,
                timeout=install_timeout,
            )
            if install_code != 0:
                return (
                    f"依赖安装失败 (退出代码: {install_code}):\n"
                    f"{install_stderr}\n{install_stdout}"
                )

            # 避免在有网络的安装阶段暴露用户脚本给依赖安装代码。
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code)

            exec_timeout = max(deadline - time.monotonic(), 1.0)
            cmd = _build_exec_cmd(
                host_tmpdir,
                memory,
                pythonpath="/tmp/_site_packages",
            )
        else:
            # 将代码写入脚本文件（避免 shell 引号转义问题）
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code)
            cmd = _build_exec_cmd(host_tmpdir, memory)
            exec_timeout = timeout

        logger.info(
            "[Python解释器] 开始执行, 超时: %ss, 库: %s, 输出文件: %s",
            timeout,
            libraries,
            send_files,
        )
        logger.debug("[Python解释器] 代码内容:\n%s", code)

        try:
            exit_code, response, error_output = await _run_docker_command(
                cmd,
                timeout=exec_timeout,
            )

            # 构建结果
            parts: list[str] = []
            if exit_code == 0:
                parts.append(
                    response if response.strip() else "代码执行成功 (无输出)。"
                )
            else:
                parts.append(
                    f"代码执行失败 (退出代码: {exit_code}):\n{error_output}\n{response}"
                )

            # 执行成功时发送文件
            if send_files and exit_code == 0:
                file_result = await _send_output_files(send_files, host_tmpdir, context)
                if file_result:
                    parts.append(file_result)
                defer_cleanup = True

            return "\n".join(parts)

        except asyncio.TimeoutError:
            return f"错误: 代码执行超时 ({timeout}s)。"

    except Exception as e:
        logger.exception("[Python解释器] 执行出错: %s", e)
        return "执行出错，请检查代码或重试"
    finally:
        if defer_cleanup:
            _schedule_output_dir_cleanup(host_tmpdir)
        else:
            shutil.rmtree(host_tmpdir, ignore_errors=True)


async def _send_output_files(
    send_files: list[str],
    host_tmpdir: str,
    context: Dict[str, Any],
) -> str:
    """发送输出文件给用户，返回状态摘要。"""
    sender = context.get("sender")
    if sender is None:
        return "文件发送失败：发送通道不可用"

    request_type = context.get("request_type")
    group_id = context.get("group_id")
    user_id = context.get("user_id")

    results: list[str] = []
    for container_path in send_files:
        resolved_host_path = _resolve_output_host_path(container_path, host_tmpdir)
        if resolved_host_path is None:
            results.append(f"文件路径非法: {container_path}")
            continue

        host_path = str(resolved_host_path)

        if not os.path.isfile(host_path):
            results.append(f"文件未找到: {container_path}")
            continue

        file_name = os.path.basename(host_path)
        ext = Path(host_path).suffix.lower()

        try:
            if ext in _IMAGE_EXTENSIONS:
                # 图片：通过 CQ 码内联发送
                await _send_image_inline(
                    sender, request_type, group_id, user_id, host_path
                )
            else:
                # 其他文件：通过文件上传接口发送
                await _send_file_upload(
                    sender, request_type, group_id, user_id, host_path, file_name
                )
            results.append(f"已发送: {file_name}")
        except Exception as e:
            logger.exception("[Python解释器] 文件发送失败: %s", container_path)
            results.append(f"发送失败: {file_name} ({e})")

    return "\n".join(results) if results else ""


async def _send_image_inline(
    sender: Any,
    request_type: str | None,
    group_id: Any,
    user_id: Any,
    host_path: str,
) -> None:
    """通过 CQ:image 内联发送图片。"""
    abs_path = Path(host_path).resolve()
    image_cq = f"[CQ:image,file=file://{abs_path}]"

    if request_type == "group" and group_id:
        await sender.send_group_message(int(group_id), image_cq, auto_history=False)
    elif user_id:
        await sender.send_private_message(int(user_id), image_cq, auto_history=False)
    else:
        raise RuntimeError("无法确定发送目标")


async def _send_file_upload(
    sender: Any,
    request_type: str | None,
    group_id: Any,
    user_id: Any,
    host_path: str,
    file_name: str,
) -> None:
    """通过文件上传接口发送文件。"""
    if request_type == "group" and group_id:
        await sender.send_group_file(int(group_id), host_path, file_name)
    elif user_id:
        await sender.send_private_file(int(user_id), host_path, file_name)
    else:
        raise RuntimeError("无法确定发送目标")
