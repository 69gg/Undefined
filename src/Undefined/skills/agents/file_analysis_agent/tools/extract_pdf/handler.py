import fitz
from pathlib import Path
from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    file_path: str = args.get("file_path", "")
    extract_images: bool = args.get("extract_images", False)

    path = Path(file_path)

    if not path.exists():
        return f"错误：文件不存在 {file_path}"

    if not path.is_file():
        return f"错误：{file_path} 不是文件"

    try:
        doc = fitz.open(str(path))
        page_count = len(doc)

        info: list[str] = []
        info.append(f"文件大小：{path.stat().st_size} 字节")
        info.append(f"页数：{page_count}")

        metadata = doc.metadata
        if metadata:
            info.append("\n文档元数据：")
            for key, value in metadata.items():
                if value:
                    info.append(f"  {key}: {value}")

        text_content = ""
        image_count = 0

        for page_num in range(page_count):
            page = doc.load_page(page_num)
            text_raw = page.get_text()
            text = str(text_raw) if text_raw else ""
            text_content += f"\n--- 第 {page_num + 1} 页 ---\n"
            text_content += text

            if extract_images:
                images = page.get_images()
                for _ in images:
                    image_count += 1

        if extract_images:
            info.append(f"\n图片数量：{image_count}")

        if not text_content.strip():
            text_content = "(文档未检测到文本内容，可能是扫描版 PDF 或图片)"

        info.append(f"\n文本内容预览（前 5000 字符）：\n{text_content[:5000]}")
        if len(text_content) > 5000:
            info.append(f"\n... (共 {len(text_content)} 字符)")

        doc.close()

        return "\n".join(info)

    except Exception as e:
        logger.exception(f"解析 PDF 失败: {e}")
        return f"解析 PDF 失败: {e}"
