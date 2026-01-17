import chardet
from pathlib import Path
from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    file_path: str = args.get("file_path", "")
    max_lines: int | None = args.get("max_lines")

    path = Path(file_path)

    if not path.exists():
        return f"错误：文件不存在 {file_path}"

    if not path.is_file():
        return f"错误：{file_path} 不是文件"

    try:
        file_size = path.stat().st_size

        with open(path, "rb") as binary_file:
            raw_data: bytes = binary_file.read()

        detected = chardet.detect(raw_data)
        encoding: str | None = detected.get("encoding") if detected else None
        confidence: float = detected.get("confidence", 0.0) if detected else 0.0

        encodings_to_try: list[str] = []
        if encoding and confidence > 0.5:
            encodings_to_try.append(encoding)
        encodings_to_try.extend(
            [
                "utf-8",
                "gbk",
                "gb2312",
                "gb18030",
                "big5",
                "shift_jis",
                "euc-kr",
                "latin-1",
            ]
        )

        file_content: str = ""
        actual_encoding: str = "unknown"
        decode_error: Exception | None = None

        for enc in encodings_to_try:
            try:
                file_content = raw_data.decode(enc)
                actual_encoding = enc
                break
            except (UnicodeDecodeError, LookupError) as e:
                decode_error = e
                continue

        if not file_content and decode_error:
            return f"错误：无法解码文件，可能是二进制文件。文件大小：{file_size} 字节"

        control_chars = sum(
            1 for c in file_content if ord(c) < 32 and c not in "\t\n\r"
        )
        if control_chars > len(file_content) * 0.05:
            return f"错误：文件包含大量控制字符，可能是二进制文件。文件大小：{file_size} 字节"

        total_lines = file_content.count("\n")
        if max_lines and total_lines > max_lines:
            lines = file_content.split("\n")[:max_lines]
            file_content = "\n".join(lines)
            truncated = True
        else:
            truncated = False

        info_lines: list[str] = []
        info_lines.append(f"文件大小：{file_size} 字节")
        info_lines.append(f"检测编码：{encoding} (置信度: {confidence:.2f})")
        info_lines.append(f"实际编码：{actual_encoding}")
        info_lines.append(f"内容行数：{total_lines}")
        if truncated:
            info_lines.append(f"已截断到前 {max_lines} 行")
        info_lines.append("")

        return "\n".join(info_lines) + file_content

    except Exception as e:
        logger.exception(f"读取文件失败: {e}")
        return f"读取文件失败: {e}"
