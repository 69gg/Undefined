#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from Undefined.webui.utils import sync_config_file  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="同步 config.toml.example 中的新配置项与注释到现有 config.toml，同时保留已有配置值。"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="目标配置文件路径，默认: config.toml",
    )
    parser.add_argument(
        "--example",
        type=Path,
        default=Path("config.toml.example"),
        help="示例配置文件路径，默认: config.toml.example",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览同步结果，不写回文件。",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="将同步后的完整 TOML 输出到标准输出。",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = sync_config_file(
            config_path=args.config,
            example_path=args.example,
            write=not args.dry_run,
        )
    except FileNotFoundError as exc:
        print(f"[sync-config] 未找到示例配置：{exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"[sync-config] 配置解析失败：{exc}", file=sys.stderr)
        return 1

    action = "预览完成" if args.dry_run else "同步完成"
    print(f"[sync-config] {action}: {args.config}")
    print(f"[sync-config] 新增路径数量: {len(result.added_paths)}")
    for path in result.added_paths:
        print(f"  + {path}")

    if args.stdout:
        print("\n--- merged config.toml ---\n")
        print(result.content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
