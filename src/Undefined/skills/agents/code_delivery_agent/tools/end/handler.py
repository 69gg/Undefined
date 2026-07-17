from __future__ import annotations

import hashlib
import logging
import os
import tarfile
import zipfile
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _group_access_error(runtime_config: Any, group_id: int) -> str:
    reason_getter = getattr(runtime_config, "group_access_denied_reason", None)
    reason = reason_getter(group_id) if callable(reason_getter) else None
    if reason == "blacklist":
        return f"上传失败：目标群 {group_id} 在黑名单内（access.blocked_group_ids）"
    return f"上传失败：目标群 {group_id} 不在允许列表内（access.allowed_group_ids）"


def _private_access_error(runtime_config: Any, user_id: int) -> str:
    reason_getter = getattr(runtime_config, "private_access_denied_reason", None)
    reason = reason_getter(user_id) if callable(reason_getter) else None
    if reason == "blacklist":
        return f"上传失败：目标用户 {user_id} 在黑名单内（access.blocked_private_ids）"
    return f"上传失败：目标用户 {user_id} 不在允许列表内（access.allowed_private_ids）"


def _should_exclude(rel_path: str, patterns: list[str]) -> bool:
    """检查路径是否匹配任一排除模式。"""
    for pattern in patterns:
        if fnmatch(rel_path, pattern):
            return True
        # 也检查路径的每一级
        parts = rel_path.split("/")
        for i in range(len(parts)):
            partial = "/".join(parts[: i + 1])
            if fnmatch(partial, pattern) or fnmatch(partial + "/", pattern):
                return True
    return False


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """结束任务，打包工作区并上传。"""

    exclude_patterns: list[str] = args.get("exclude_patterns", [])
    if not isinstance(exclude_patterns, list):
        exclude_patterns = []
    archive_name = str(args.get("archive_name", "")).strip() or "delivery"
    archive_format_arg = str(args.get("archive_format", "")).strip().lower()
    summary = str(args.get("summary", "")).strip()

    workspace: Path | None = context.get("workspace")
    task_dir: Path | None = context.get("task_dir")
    if not workspace or not task_dir:
        return "错误：workspace 或 task_dir 未设置"

    ws_resolved = workspace.resolve()
    if not ws_resolved.exists():
        return "错误：workspace 目录不存在"

    config = context.get("config")
    default_archive_format = "zip"
    if config:
        default_archive_format = getattr(
            config, "code_delivery_default_archive_format", "zip"
        )
    default_archive_format = str(default_archive_format).strip().lower()
    if default_archive_format not in ("zip", "tar.gz"):
        default_archive_format = "zip"

    archive_format = archive_format_arg or default_archive_format
    if archive_format not in ("zip", "tar.gz"):
        return "错误：archive_format 仅支持 zip 或 tar.gz"

    # 收集要打包的文件
    files_to_pack: list[Path] = []
    for root, _dirs, filenames in os.walk(ws_resolved):
        for fname in filenames:
            full = Path(root) / fname
            rel = str(full.relative_to(ws_resolved))
            if not _should_exclude(rel, exclude_patterns):
                files_to_pack.append(full)

    if not files_to_pack:
        return "错误：打包后无文件（可能排除规则过于严格）"

    # 打包
    artifacts_dir = task_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    if archive_format == "tar.gz":
        archive_path = artifacts_dir / f"{archive_name}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            for f in files_to_pack:
                arcname = str(f.relative_to(ws_resolved))
                tar.add(f, arcname=arcname)
    else:
        archive_path = artifacts_dir / f"{archive_name}.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files_to_pack:
                arcname = str(f.relative_to(ws_resolved))
                zf.write(f, arcname=arcname)

    archive_size = archive_path.stat().st_size
    archive_hash = _file_hash(str(archive_path))

    # 检查大小限制
    max_size_mb: int = 200
    if config:
        max_size_mb = getattr(config, "code_delivery_max_archive_size_mb", 200)
    if archive_size > max_size_mb * 1024 * 1024:
        return (
            f"错误：归档文件过大 ({archive_size / 1024 / 1024:.1f}MB)，"
            f"超过限制 {max_size_mb}MB"
        )

    # 上传
    sender = context.get("sender")
    target_type: str = context.get("target_type", "")
    target_id: int = context.get("target_id", 0)
    runtime_config = context.get("runtime_config") or context.get("config")

    upload_status = "未上传"
    access_error: str | None = None
    if runtime_config is not None:
        if target_type == "group" and not runtime_config.is_group_allowed(target_id):
            access_error = _group_access_error(runtime_config, target_id)
        if target_type == "private" and not runtime_config.is_private_allowed(
            target_id
        ):
            access_error = _private_access_error(runtime_config, target_id)

    if access_error is not None:
        upload_status = access_error
    elif sender and target_type and target_id:
        try:
            abs_path = str(archive_path.resolve())
            if target_type == "group":
                await sender.send_group_file(
                    target_id,
                    abs_path,
                    name=archive_path.name,
                )
            else:
                await sender.send_private_file(
                    target_id,
                    abs_path,
                    name=archive_path.name,
                )
            upload_status = "上传成功"

            # 发送摘要消息
            if summary:
                msg = f"📦 代码交付完成\n\n{summary}\n\n文件: {archive_path.name} ({archive_size / 1024:.1f}KB)"
                if target_type == "group":
                    await sender.send_group_message(target_id, msg)
                else:
                    await sender.send_private_message(target_id, msg)
        except Exception as exc:
            logger.exception("上传文件失败")
            upload_status = f"上传失败: {exc}"
    else:
        upload_status = "未配置上传目标，文件已保留在本地"

    # 标记会话结束
    context["conversation_ended"] = True

    return (
        f"归档: {archive_path.name}\n"
        f"大小: {archive_size / 1024:.1f}KB\n"
        f"文件数: {len(files_to_pack)}\n"
        f"SHA256: {archive_hash[:16]}...\n"
        f"状态: {upload_status}"
    )
