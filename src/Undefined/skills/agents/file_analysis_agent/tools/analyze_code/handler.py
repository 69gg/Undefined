import chardet
from pathlib import Path
from typing import Any, Dict
import re
import logging

logger = logging.getLogger(__name__)

LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".jsx": "React JavaScript",
    ".tsx": "React TypeScript",
    ".c": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".cs": "C#",
    ".java": "Java",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".m": "Objective-C / MATLAB/Octave",
    ".mm": "Objective-C++",
    ".pyw": "Python (GUI)",
    ".lua": "Lua",
    ".r": "R",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Bash",
    ".zsh": "Zsh",
    ".ps1": "PowerShell",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".xml": "XML",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".less": "LESS",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".erl": "Erlang",
    ".hrl": "Erlang Header",
    ".ml": "OCaml",
    ".mli": "OCaml Interface",
    ".hs": "Haskell",
    ".lhs": "Literate Haskell",
    ".jl": "Julia",
    ".mat": "MATLAB",
    ".pl": "Perl",
    ".pm": "Perl Module",
    ".t": "Perl Test",
    ".awk": "AWK",
    ".groovy": "Groovy",
    ".gradle": "Gradle",
    ".proto": "Protocol Buffer",
    ".thrift": "Thrift",
}

COMMENT_PATTERNS: dict[str, tuple[str | None, str | None]] = {
    "Python": ('"""', '"""'),
    "JavaScript": ("/*", "*/"),
    "TypeScript": ("/*", "*/"),
    "Java": ("/*", "*/"),
    "Kotlin": ("/*", "*/"),
    "Go": ("/*", "*/"),
    "Rust": ("/*", "*/"),
    "Ruby": ("=begin", "=end"),
    "PHP": ("/*", "*/"),
    "C": ("/*", "*/"),
    "C++": ("/*", "*/"),
    "C#": ("/*", "*/"),
    "Swift": ("/*", "*/"),
    "SQL": ("/*", "*/"),
    "Shell": ("#", None),
    "Bash": ("#", None),
    "CSS": ("/*", "*/"),
    "HTML": ("<!--", "-->"),
    "XML": ("<!--", "-->"),
    "YAML": ("#", None),
    "JSON": (None, None),
    "Lua": ("--[[", "]]"),
    "Dart": ("/*", "*/"),
    "Scala": ("/*", "*/"),
    "Elixir": ("#", None),
    "Erlang": ("%", None),
    "Haskell": ("{-", "-}"),
    "Julia": ("#=", "=#"),
    "Perl": ("#", None),
    "Groovy": ("/*", "*/"),
}


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    file_path: str = args.get("file_path", "")
    path = Path(file_path)

    if not path.exists():
        return f"错误：文件不存在 {file_path}"

    if not path.is_file():
        return f"错误：{file_path} 不是文件"

    try:
        with open(path, "rb") as binary_file:
            raw_data: bytes = binary_file.read()

        detected = chardet.detect(raw_data)
        encoding: str | None = detected.get("encoding") if detected else "utf-8"
        confidence: float = detected.get("confidence", 0) if detected else 0

        if encoding is None or confidence < 0.5:
            encoding = "utf-8"

        try:
            content = raw_data.decode(encoding)
        except UnicodeDecodeError:
            content = raw_data.decode("utf-8")

        file_size = path.stat().st_size
        language = _detect_language(path, content)

        lines = content.split("\n")
        total_lines = len(lines)
        code_lines = sum(
            1 for line in lines if line.strip() and not _is_comment(line, language)
        )
        comment_lines = sum(1 for line in lines if _is_comment(line, language))
        blank_lines = sum(1 for line in lines if not line.strip())

        info: list[str] = []
        info.append(f"文件大小：{file_size} 字节")
        info.append(f"检测编码：{encoding} (置信度: {confidence:.2f})")
        info.append(f"编程语言：{language}")
        info.append(f"总行数：{total_lines}")
        info.append(f"代码行数：{code_lines}")
        info.append(f"注释行数：{comment_lines}")
        info.append(f"空行数：{blank_lines}")

        if language != "Plain Text":
            imports = _extract_imports(content, language)
            functions = _extract_functions(content, language)
            classes = _extract_classes(content, language)
            comment_blocks = _extract_comment_blocks(content, language)

            if imports:
                info.append(f"\n导入模块 ({len(imports)}):")
                for imp in imports[:20]:
                    info.append(f"  - {imp}")
                if len(imports) > 20:
                    info.append(f"  ... (还有 {len(imports) - 20} 个)")

            if classes:
                info.append(f"\n类定义 ({len(classes)}):")
                for cls in classes[:10]:
                    info.append(f"  - {cls}")
                if len(classes) > 10:
                    info.append(f"  ... (还有 {len(classes) - 10} 个)")

            if functions:
                info.append(f"\n函数定义 ({len(functions)}):")
                for func in functions[:15]:
                    info.append(f"  - {func}")
                if len(functions) > 15:
                    info.append(f"  ... (还有 {len(functions) - 15} 个)")

            if comment_blocks:
                info.append(f"\n文档注释 ({len(comment_blocks)}):")
                for i, comment in enumerate(comment_blocks[:5], 1):
                    lines_preview = "\n".join(comment.split("\n")[:3])
                    if len(comment.split("\n")) > 3:
                        lines_preview += "..."
                    info.append(f"  {i}. {lines_preview}")
                if len(comment_blocks) > 5:
                    info.append(f"  ... (还有 {len(comment_blocks) - 5} 个)")

        content_preview = "\n".join(lines[:50])
        if total_lines > 50:
            content_preview += f"\n... (共 {total_lines} 行，已显示前 50 行)"

        info.append(f"\n--- 文件内容预览 ---\n{content_preview}")

        return "\n".join(info)

    except Exception as e:
        logger.exception(f"分析代码失败: {e}")
        return f"分析代码失败: {e}"


def _detect_language(path: Path, content: str) -> str:
    ext = path.suffix.lower()
    language = LANGUAGE_MAP.get(ext, "Plain Text")

    if language == "Plain Text":
        if content.startswith("#!/usr/bin/python") or content.startswith(
            "#!/usr/bin/env python"
        ):
            language = "Python"
        elif content.startswith("#!/usr/bin/node") or content.startswith(
            "#!/usr/bin/env node"
        ):
            language = "JavaScript"
        elif content.startswith("#!/bin/bash") or content.startswith("#!/usr/bin/bash"):
            language = "Bash"

    return language


def _is_comment(line: str, language: str) -> bool:
    line = line.strip()
    if not line:
        return False

    comment_starts = ["#", "//", "--", "%", ";", '"']
    for cs in comment_starts:
        if line.startswith(cs):
            return True

    if language in ("HTML", "XML", "CSS"):
        if "<!--" in line:
            return True

    return False


def _extract_imports(content: str, language: str) -> list[str]:
    """从代码中提取导入的模块

    参数:
        content: 代码内容
        language: 编程语言

    返回:
        导入的模块列表
    """
    imports: list[str] = []
    patterns: list[tuple[str, str]] = [
        (r"^import\s+([\w.]+)", "Python"),
        (r"^from\s+([\w.]+)\s+import", "Python"),
        (r"^import\s+\{([^}]+)\}", "JavaScript"),
        (r"^import\s+([\w{}/.]+)", "JavaScript"),
        (r"^use\s+crate::([\w:]+)", "Rust"),
        (r"^use\s+([\w:]+)", "Rust"),
        (r'^#include\s+[<"]([^\s>""]+)', "C/C++"),
        (r"^package\s+([\w.]+)", "Java"),
        (r"^import\s+([\w.]+);", "Java"),
        (r"^use\s+([\w:]+)", "Go"),
        (r'^require\s+[\'"]([^\'"]+)[\'"]', "Ruby"),
        (r"^use\s+([\w\\]+)", "PHP"),
    ]

    for line in content.split("\n"):
        line = line.strip()
        for pattern, lang in patterns:
            if lang != language:
                continue
            match = re.match(pattern, line)
            if match:
                imports.append(match.group(1))

    return list(dict.fromkeys(imports))


# 函数定义正则表达式映射
_FUNCTION_PATTERNS: dict[str, str] = {
    "Python": r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
    "JavaScript": r"(?:function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)|const\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=\s*(?:async\s+)?\(",
    "TypeScript": r"(?:function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)|const\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=\s*(?:async\s+)?\(",
    "Java": r"(?:public|private|protected|static|\s)*\s*(?:void|[\w<>]+)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
    "Kotlin": r"fun\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
    "Go": r"func\s+(?:[(\w]+\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
    "Rust": r"fn\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
    "C": r"(?:static\s+)?(?:void|[\w*]+)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
    "C++": r"(?:static\s+)?(?:void|[\w*]+)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
    "Ruby": r"def\s+([a-zA-Z_][a-zA-Z0-9_?!]*)",
    "PHP": r"function\s+([a-zA-Z_\x7f-\xff][a-zA-Z0-9_\x7f-\xff]*)\s*\(",
    "Swift": r"func\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
    "Shell": r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*\(\)",
}


def _extract_function_name_from_match(match: re.Match[str]) -> str | None:
    """从正则匹配结果中提取函数名。

    Args:
        match: 正则匹配结果

    Returns:
        函数名，未找到时返回 None
    """
    # 尝试获取第二个捕获组（用于 const function 形式）
    if match.group(2):
        return match.group(2)
    # 返回第一个捕获组
    return match.group(1)


def _extract_functions(content: str, language: str) -> list[str]:
    """从代码中提取函数定义。

    Args:
        content: 代码内容
        language: 编程语言

    Returns:
        函数名列表
    """
    functions: list[str] = []

    # 获取对应语言的正则表达式
    pattern = _FUNCTION_PATTERNS.get(language)
    if not pattern:
        return functions

    # 遍历每一行，提取函数名
    for line in content.split("\n"):
        line = line.strip()
        match = re.match(pattern, line)
        if match:
            func_name = _extract_function_name_from_match(match)
            if func_name:
                functions.append(func_name)

    return functions


def _extract_classes(content: str, language: str) -> list[str]:
    """从代码中提取类定义

    参数:
        content: 代码内容
        language: 编程语言

    返回:
        类名列表
    """
    classes: list[str] = []
    patterns: dict[str, str] = {
        "Python": r"^class\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        "JavaScript": r"class\s+([a-zA-Z_$][a-zA-Z0-9_$]*)",
        "TypeScript": r"class\s+([a-zA-Z_$][a-zA-Z0-9_$]*)",
        "Java": r"(?:public|private|protected|\s)*\s*class\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        "Kotlin": r"class\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        "Go": r"type\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+struct",
        "Rust": r"struct\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        "C++": r"class\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        "C#": r"class\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        "Ruby": r"^class\s+([A-Z][a-zA-Z0-9_]*)",
        "PHP": r"class\s+([a-zA-Z_\x7f-\xff][a-zA-Z0-9_\x7f-\xff]*)",
        "Swift": r"class\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    }

    pattern = patterns.get(language)
    if not pattern:
        return classes

    for line in content.split("\n"):
        line = line.strip()
        match = re.match(pattern, line)
        if match:
            classes.append(match.group(1))

    return classes


def _is_line_comment(line: str) -> bool:
    """检查行是否为单行注释。

    Args:
        line: 代码行

    Returns:
        如果是单行注释返回 True，否则返回 False
    """
    stripped = line.strip()
    comment_prefixes = ("#", "//", "--", "%", ";", '"')
    return stripped.startswith(comment_prefixes)


def _is_block_end(line: str, end_delim: str) -> bool:
    """检查行是否包含块注释结束标记。

    Args:
        line: 代码行
        end_delim: 结束分隔符

    Returns:
        如果包含结束标记返回 True，否则返回 False
    """
    if not end_delim:
        return False
    line_stripped = line.strip()
    return line_stripped.endswith(end_delim) or end_delim in line_stripped


def _process_block_start(
    line: str,
    start_delim: str,
    in_block: bool,
    current_block: list[str],
) -> tuple[bool, list[str]]:
    """处理块注释开始。

    Args:
        line: 代码行
        start_delim: 开始分隔符
        in_block: 是否已在块中
        current_block: 当前块内容

    Returns:
        (是否在块中, 当前块内容)
    """
    if in_block:
        return in_block, current_block

    line_stripped = line.strip()
    if line_stripped.startswith(start_delim):
        return True, [line]

    return in_block, current_block


def _process_block_line(
    line: str,
    end_delim: str | None,
    in_block: bool,
    current_block: list[str],
    blocks: list[str],
) -> tuple[bool, list[str]]:
    """处理块注释中的行。

    Args:
        line: 代码行
        end_delim: 结束分隔符
        in_block: 是否已在块中
        current_block: 当前块内容
        blocks: 已收集的块列表

    Returns:
        (是否在块中, 当前块内容)
    """
    current_block.append(line)

    # 有结束分隔符的情况
    if end_delim:
        if _is_block_end(line, end_delim):
            _add_block_if_valid(blocks, current_block)
            return False, []
        return in_block, current_block

    # 无结束分隔符（单行注释）的情况
    if not _is_line_comment(line):
        # 遇到非注释行，结束块
        current_block.pop()  # 移除刚才添加的非注释行
        _add_block_if_valid(blocks, current_block)
        return False, []

    return in_block, current_block


def _extract_comment_blocks(content: str, language: str) -> list[str]:
    """提取代码中的块注释。

    支持两种类型的注释：
    1. 有明确开始和结束标记的块注释（如 /* ... */）
    2. 连续的单行注释（如 # ...）

    Args:
        content: 代码内容
        language: 编程语言

    Returns:
        注释块列表
    """
    blocks: list[str] = []

    # 检查语言是否支持注释
    if language not in COMMENT_PATTERNS:
        return blocks

    start_delim, end_delim = COMMENT_PATTERNS[language]
    if start_delim is None:
        return blocks

    lines = content.split("\n")
    in_block = False
    current_block: list[str] = []

    for line in lines:
        # 处理块注释开始
        in_block, current_block = _process_block_start(
            line, start_delim, in_block, current_block
        )

        # 如果在块中，处理当前行
        if in_block:
            in_block, current_block = _process_block_line(
                line, end_delim, in_block, current_block, blocks
            )

    # 处理文件末尾遗留的块
    if current_block:
        _add_block_if_valid(blocks, current_block)

    return blocks


def _add_block_if_valid(blocks: list[str], current_block: list[str]) -> None:
    """如果块内容有效且长度足够，则添加到列表。

    Args:
        blocks: 目标列表
        current_block: 当前块内容
    """
    block_content = "\n".join(current_block)
    if len(block_content) > 20:
        blocks.append(block_content)
