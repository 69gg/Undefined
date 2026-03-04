import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Docker 执行配置
DOCKER_IMAGE = "python:3.11-slim"
MEMORY_LIMIT = "128m"
MEMORY_LIMIT_WITH_LIBS = "512m"
CPU_LIMIT = "0.5"
TIMEOUT = 480  # 8 分钟
TIMEOUT_WITH_LIBS = 600  # 10 分钟（pip 安装需要更多时间）

# 图片扩展名（内联发送而非文件附件）
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"})

# 安全：库名仅允许 PyPI 合法字符，必须以字母/数字开头（防止 -r/-e/--index-url 注入）
_SAFE_LIB_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-\[\],<>=!~]*$")


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

    # 验证文件路径必须在 /tmp/ 下
    for fpath in send_files:
        if not fpath.startswith("/tmp/"):
            return f"错误: 输出文件路径必须在 /tmp/ 目录下: '{fpath}'"

    has_libs = bool(libraries)
    memory = MEMORY_LIMIT_WITH_LIBS if has_libs else MEMORY_LIMIT
    timeout = TIMEOUT_WITH_LIBS if has_libs else TIMEOUT

    # 创建宿主机临时目录，绑定挂载到容器 /tmp
    host_tmpdir = tempfile.mkdtemp(prefix="pyinterp_")

    try:
        # 将代码写入脚本文件（避免 shell 引号转义问题）
        script_path = os.path.join(host_tmpdir, "_script.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        # 构建 docker 命令
        cmd: list[str] = [
            "docker",
            "run",
            "--rm",
            "--memory",
            memory,
            "--cpus",
            CPU_LIMIT,
            "-v",
            f"{host_tmpdir}:/tmp",
        ]

        if has_libs:
            # 需要网络下载包、需要写权限安装包
            req_path = os.path.join(host_tmpdir, "_requirements.txt")
            with open(req_path, "w", encoding="utf-8") as f:
                for lib in libraries:
                    f.write(lib + "\n")
            cmd.append(DOCKER_IMAGE)
            # pip install → 运行代码 → 修正文件权限以便宿主机清理
            cmd.extend(
                [
                    "sh",
                    "-c",
                    "pip install --quiet -r /tmp/_requirements.txt "
                    "&& python /tmp/_script.py; "
                    "_e=$?; chmod -R a+rw /tmp 2>/dev/null; exit $_e",
                ]
            )
        else:
            # 无需网络、只读文件系统
            cmd.extend(["--network", "none", "--read-only"])
            cmd.append(DOCKER_IMAGE)
            cmd.extend(["python", "/tmp/_script.py"])

        logger.info(
            "[Python解释器] 开始执行, 超时: %ss, 库: %s, 输出文件: %s",
            timeout,
            libraries,
            send_files,
        )
        logger.debug("[Python解释器] 代码内容:\n%s", code)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )

            exit_code = process.returncode
            response = stdout_bytes.decode("utf-8", errors="replace")
            error_output = stderr_bytes.decode("utf-8", errors="replace")

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

            return "\n".join(parts)

        except asyncio.TimeoutError:
            try:
                process.terminate()
                await process.wait()
            except Exception as e:
                logger.error("[Python解释器] 终止超时进程失败: %s", e)
            return f"错误: 代码执行超时 ({timeout}s)。"

    except Exception as e:
        logger.exception("[Python解释器] 执行出错: %s", e)
        return "执行出错，请检查代码或重试"
    finally:
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
        # /tmp/output.png → {host_tmpdir}/output.png
        relative = container_path.removeprefix("/tmp/")
        host_path = os.path.join(host_tmpdir, relative)

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
