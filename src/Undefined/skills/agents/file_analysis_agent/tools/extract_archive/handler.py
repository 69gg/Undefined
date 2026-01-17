from pathlib import Path
from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    file_path: str = args.get("file_path", "")
    action: str = args.get("action", "list")
    extract_path: str | None = args.get("extract_path")

    path = Path(file_path)

    if not path.exists():
        return f"错误：文件不存在 {file_path}"

    if not path.is_file():
        return f"错误：{file_path} 不是文件"

    suffix = path.suffix.lower()

    try:
        if suffix == ".zip":
            return await _extract_zip(path, action, extract_path)
        elif suffix in [".tar", ".gz", ".bz2", ".xz"]:
            return await _extract_tar(path, action, extract_path)
        elif suffix == ".7z":
            return await _extract_7z(path, action, extract_path)
        elif suffix == ".rar":
            return await _extract_rar(path, action, extract_path)
        else:
            return f"不支持的压缩格式: {suffix}"

    except Exception as e:
        logger.exception(f"解析压缩包失败: {e}")
        return f"解析压缩包失败: {e}"


async def _extract_zip(path: Path, action: str, extract_path: str | None) -> str:
    import zipfile

    with zipfile.ZipFile(path, "r") as zip_ref:
        file_list = zip_ref.namelist()
        total_size = sum(info.file_size for info in zip_ref.infolist())

    info: list[str] = []
    info.append(f"文件大小：{path.stat().st_size} 字节")
    info.append(f"压缩包内文件数：{len(file_list)}")
    info.append(f"解压后总大小：{total_size} 字节")

    if action == "list":
        info.append("\n文件列表（前 100 个）：")
        for i, name in enumerate(file_list[:100], 1):
            info.append(f"  {i}. {name}")
        if len(file_list) > 100:
            info.append(f"  ... (共 {len(file_list)} 个文件)")
        return "\n".join(info)

    else:
        if extract_path:
            target_dir = Path(extract_path)
        else:
            target_dir = path.parent / f"extracted_{path.stem}"
            target_dir.mkdir(exist_ok=True)

        with zipfile.ZipFile(path, "r") as zip_ref:
            zip_ref.extractall(target_dir)

        info.append(f"\n已解压到：{target_dir}")
        info.append(f"解压文件数：{len(file_list)}")
        info.append("\n文件列表（前 50 个）：")
        for i, name in enumerate(file_list[:50], 1):
            info.append(f"  {i}. {name}")
        if len(file_list) > 50:
            info.append(f"  ... (共 {len(file_list)} 个文件)")

        return "\n".join(info)


async def _extract_tar(path: Path, action: str, extract_path: str | None) -> str:
    import tarfile

    with tarfile.open(path, "r:*") as tar_ref:
        members = tar_ref.getmembers()
        file_list = [m.name for m in members]
        total_size = sum(m.size for m in members)

    info: list[str] = []
    info.append(f"文件大小：{path.stat().st_size} 字节")
    info.append(f"压缩包内文件数：{len(file_list)}")
    info.append(f"解压后总大小：{total_size} 字节")

    if action == "list":
        info.append("\n文件列表（前 100 个）：")
        for i, name in enumerate(file_list[:100], 1):
            info.append(f"  {i}. {name}")
        if len(file_list) > 100:
            info.append(f"  ... (共 {len(file_list)} 个文件)")
        return "\n".join(info)

    else:
        if extract_path:
            target_dir = Path(extract_path)
        else:
            target_dir = path.parent / f"extracted_{path.stem}"
            target_dir.mkdir(exist_ok=True)

        with tarfile.open(path, "r:*") as tar_ref:
            tar_ref.extractall(target_dir)

        info.append(f"\n已解压到：{target_dir}")
        info.append(f"解压文件数：{len(file_list)}")

        return "\n".join(info)


async def _extract_7z(path: Path, action: str, extract_path: str | None) -> str:
    import py7zr

    with py7zr.SevenZipFile(path, "r") as archive:
        file_list: list[str] = []
        total_size = 0
        for file_info in archive.files:
            file_list.append(file_info.filename)
            total_size += file_info.uncompressed

    info: list[str] = []
    info.append(f"文件大小：{path.stat().st_size} 字节")
    info.append(f"压缩包内文件数：{len(file_list)}")
    info.append(f"解压后总大小：{total_size} 字节")

    if action == "list":
        info.append("\n文件列表（前 100 个）：")
        for i, name in enumerate(file_list[:100], 1):
            info.append(f"  {i}. {name}")
        if len(file_list) > 100:
            info.append(f"  ... (共 {len(file_list)} 个文件)")
        return "\n".join(info)

    else:
        if extract_path:
            target_dir = Path(extract_path)
        else:
            target_dir = path.parent / f"extracted_{path.stem}"
            target_dir.mkdir(exist_ok=True)

        with py7zr.SevenZipFile(path, "r") as archive:
            archive.extractall(target_dir)

        info.append(f"\n已解压到：{target_dir}")
        info.append(f"解压文件数：{len(file_list)}")

        return "\n".join(info)


async def _extract_rar(path: Path, action: str, extract_path: str | None) -> str:
    import rarfile

    with rarfile.RarFile(path, "r") as rar_ref:
        file_list = rar_ref.namelist()
        total_size = sum(info.file_size for info in rar_ref.infolist())

    info: list[str] = []
    info.append(f"文件大小：{path.stat().st_size} 字节")
    info.append(f"压缩包内文件数：{len(file_list)}")
    info.append(f"解压后总大小：{total_size} 字节")

    if action == "list":
        info.append("\n文件列表（前 100 个）：")
        for i, name in enumerate(file_list[:100], 1):
            info.append(f"  {i}. {name}")
        if len(file_list) > 100:
            info.append(f"  ... (共 {len(file_list)} 个文件)")
        return "\n".join(info)

    else:
        if extract_path:
            target_dir = Path(extract_path)
        else:
            target_dir = path.parent / f"extracted_{path.stem}"
            target_dir.mkdir(exist_ok=True)

        with rarfile.RarFile(path, "r") as rar_ref:
            rar_ref.extractall(target_dir)

        info.append(f"\n已解压到：{target_dir}")
        info.append(f"解压文件数：{len(file_list)}")

        return "\n".join(info)
