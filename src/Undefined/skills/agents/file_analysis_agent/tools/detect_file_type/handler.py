import platform
import subprocess
from pathlib import Path
from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)

MAGIC_NUMBERS: dict[bytes, str] = {
    # 常用压缩格式
    b"\x50\x4b\x03\x04": "ZIP Archive",
    b"\x50\x4b\x05\x06": "ZIP Archive (empty)",
    b"\x50\x4b\x07\x08": "ZIP Archive (spanned)",
    # 文档格式
    b"\x25\x50\x44\x46": "PDF Document",
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1": "Microsoft Office Document (OLE)",
    b"\x50\x4b\x03\x04\x14\x00\x06\x00": "OpenDocument Format",
    # 图片格式
    b"\xff\xd8\xff": "JPEG Image",
    b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a": "PNG Image",
    b"GIF8": "GIF Image",
    b"\x49\x49\x2a\x00": "TIFF Image (little-endian)",
    b"\x4d\x4d\x00\x2a": "TIFF Image (big-endian)",
    b"\x42\x4d": "BMP Image",
    # 音频格式
    b"\x49\x44\x33": "MP3 Audio (ID3)",
    b"\xff\xfb": "MP3 Audio (MPEG)",
    b"\xff\xfa": "MP3 Audio (MPEG)",
    b"\xff\xf3": "MP3 Audio (MPEG)",
    b"\xff\xf2": "MP3 Audio (MPEG)",
    # 视频格式
    b"\x1a\x45\xdf\xa3": "WebM/Matroska Video",
    b"\x00\x00\x00\x18ftypmp42": "MP4 Video (isom)",
    b"\x00\x00\x00\x1cftypisom": "MP4 Video (isom)",
    b"\x00\x00\x00\x20ftypmp41": "MP4 Video (isom)",
    b"\x52\x49\x46\x46": "AVI/RIFF Video",
    # 其他压缩格式
    b"\x1f\x8b": "GZIP Archive",
    b"\xfd7zXZ": "XZ Archive",
    b"BZh": "BZIP2 Archive",
}

EXTENSION_MAP: dict[str, str] = {
    ".pdf": "PDF Document",
    ".docx": "Microsoft Word Document",
    ".doc": "Microsoft Word Document (legacy)",
    ".pptx": "Microsoft PowerPoint Document",
    ".ppt": "Microsoft PowerPoint Document (legacy)",
    ".xlsx": "Microsoft Excel Document",
    ".xls": "Microsoft Excel Document (legacy)",
    ".odt": "OpenDocument Text",
    ".ods": "OpenDocument Spreadsheet",
    ".odp": "OpenDocument Presentation",
    ".txt": "Plain Text",
    ".md": "Markdown Document",
    ".rst": "reStructuredText Document",
    ".log": "Log File",
    ".json": "JSON Data",
    ".yaml": "YAML Data",
    ".yml": "YAML Data",
    ".xml": "XML Data",
    ".toml": "TOML Data",
    ".ini": "INI Configuration",
    ".py": "Python Source Code",
    ".js": "JavaScript Source Code",
    ".ts": "TypeScript Source Code",
    ".c": "C Source Code",
    ".cpp": "C++ Source Code",
    ".cc": "C++ Source Code",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".java": "Java Source Code",
    ".go": "Go Source Code",
    ".rs": "Rust Source Code",
    ".php": "PHP Source Code",
    ".rb": "Ruby Source Code",
    ".swift": "Swift Source Code",
    ".kt": "Kotlin Source Code",
    ".sql": "SQL Script",
    ".r": "R Source Code",
    ".lua": "Lua Script",
    ".sh": "Shell Script",
    ".bash": "Bash Script",
    ".html": "HTML Document",
    ".htm": "HTML Document",
    ".css": "CSS Stylesheet",
    ".scss": "SCSS Stylesheet",
    ".less": "LESS Stylesheet",
    ".vue": "Vue Component",
    ".jsx": "React Component",
    ".tsx": "React TypeScript Component",
    ".jpg": "JPEG Image",
    ".jpeg": "JPEG Image",
    ".png": "PNG Image",
    ".gif": "GIF Image",
    ".bmp": "BMP Image",
    ".webp": "WebP Image",
    ".svg": "SVG Image",
    ".ico": "ICO Icon",
    ".psd": "Photoshop Document",
    ".mp3": "MP3 Audio",
    ".wav": "WAV Audio",
    ".flac": "FLAC Audio",
    ".aac": "AAC Audio",
    ".m4a": "MPEG-4 Audio",
    ".ogg": "OGG Audio",
    ".wma": "Windows Media Audio",
    ".mp4": "MP4 Video",
    ".avi": "AVI Video",
    ".mov": "QuickTime Video",
    ".mkv": "Matroska Video",
    ".webm": "WebM Video",
    ".flv": "Flash Video",
    ".wmv": "Windows Media Video",
    ".zip": "ZIP Archive",
    ".tar": "TAR Archive",
    ".gz": "GZIP Archive",
    ".tgz": "GZIP-compressed TAR",
    ".bz2": "BZIP2 Archive",
    ".xz": "XZ Archive",
    ".7z": "7-Zip Archive",
    ".rar": "RAR Archive",
    ".exe": "Windows Executable",
    ".dll": "Windows Dynamic Library",
    ".so": "Linux Shared Library",
    ".dylib": "macOS Dynamic Library",
    ".class": "Java Bytecode",
    ".jar": "Java Archive",
    ".war": "Java Web Archive",
    ".apk": "Android Package",
    ".ipa": "iOS App Package",
    ".deb": "Debian Package",
    ".rpm": "RPM Package",
    ".dmg": "macOS Disk Image",
    ".iso": "ISO Disk Image",
    ".csv": "CSV Data",
    ".tsv": "TSV Data",
}


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """执行文件类型检测

    检测流程：
    1. Linux 系统优先使用 `file` 命令
    2. 其他系统或 file 命令失败时，使用文件头魔数 (Magic Number) 检测
    3. 最后尝试使用文件扩展名检测
    4. 如果都失败，返回 Unknown

    参数:
        args: 工具参数
        context: 执行上下文

    返回:
        检测结果描述
    """
    file_path: str = args.get("file_path", "")
    path = Path(file_path)

    if not path.exists():
        return f"错误：文件不存在 {file_path}"

    if not path.is_file():
        return f"错误：{file_path} 不是文件"

    try:
        file_size = path.stat().st_size
        system = platform.system()

        if system == "Linux":
            result = _detect_by_file_command(path, file_size)
            if result:
                return result
        else:
            result = _detect_by_magic_number(path, file_size)
            if result:
                return result

        result = _detect_by_extension(path)
        if result:
            return result

        return f"Unknown file type (大小: {file_size} 字节)"

    except Exception as e:
        logger.exception(f"检测文件类型失败: {e}")
        return f"检测文件类型失败: {e}"


def _detect_by_file_command(path: Path, file_size: int) -> str | None:
    try:
        result = subprocess.run(
            ["file", "-b", "-L", str(path)], capture_output=True, text=True, timeout=5
        )
        output = result.stdout.strip()
        if output:
            return f"{output} (大小: {file_size} 字节)"
    except Exception as e:
        logger.warning(f"file 命令执行失败: {e}")
    return None


def _detect_by_magic_number(path: Path, file_size: int) -> str | None:
    try:
        with open(path, "rb") as f:
            header = f.read(32)

        for magic, file_type in MAGIC_NUMBERS.items():
            if header.startswith(magic):
                return f"{file_type} (大小: {file_size} 字节)"
    except Exception as e:
        logger.warning(f"魔数检测失败: {e}")
    return None


def _detect_by_extension(path: Path) -> str | None:
    ext = path.suffix.lower()
    file_type = EXTENSION_MAP.get(ext)
    if file_type:
        return file_type
    return None
