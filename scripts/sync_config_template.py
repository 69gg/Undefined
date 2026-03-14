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
    parser.add_argument(
        "--prune",
        action="store_true",
        help="删除存在于 config.toml 但不存在于 config.toml.example 中的配置项（危险操作，需二次确认）。",
    )
    return parser


def _confirm_prune(removed_paths: list[str]) -> bool:
    """显示即将删除的路径并请求用户二次确认。"""
    print(
        "\n\033[1;31m[sync-config] ⚠ 危险操作：以下配置项不存在于模板中，将被永久删除：\033[0m"
    )
    for path in removed_paths:
        print(f"  \033[31m- {path}\033[0m")
    print()
    try:
        answer = input(
            "\033[1;33m确认删除以上配置项？此操作不可撤销。输入 yes 确认: \033[0m"
        )
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer.strip().lower() == "yes"


def _initial_action_label(*, dry_run: bool, prune: bool) -> str:
    if dry_run:
        return "预览完成"
    if prune:
        return "分析完成"
    return "同步完成"


def main() -> int:
    args = build_parser().parse_args()

    # 第一轮：不带 prune 的常规同步（或 dry-run 预览）
    try:
        result = sync_config_file(
            config_path=args.config,
            example_path=args.example,
            write=not args.dry_run and not args.prune,
        )
    except FileNotFoundError as exc:
        print(f"[sync-config] 未找到示例配置：{exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"[sync-config] 配置解析失败：{exc}", file=sys.stderr)
        return 1

    action = _initial_action_label(dry_run=args.dry_run, prune=args.prune)
    print(f"[sync-config] {action}: {args.config}")
    print(f"[sync-config] 新增路径数量: {len(result.added_paths)}")
    for path in result.added_paths:
        print(f"  + {path}")

    if result.removed_paths:
        print(f"[sync-config] 多余路径数量: {len(result.removed_paths)}")
        for path in result.removed_paths:
            print(f"  - {path}")

    # --prune 流程：确认后带 prune 重新同步
    if args.prune and result.removed_paths:
        if args.dry_run:
            print("\n[sync-config] --dry-run 模式，跳过删除。")
        elif _confirm_prune(result.removed_paths):
            result = sync_config_file(
                config_path=args.config,
                example_path=args.example,
                write=True,
                prune=True,
            )
            print(
                f"\033[1;32m[sync-config] 已删除 {len(result.removed_paths)} 个多余配置项并写回文件。\033[0m"
            )
        else:
            # 用户取消 prune，仍执行不带 prune 的常规同步
            sync_config_file(
                config_path=args.config,
                example_path=args.example,
                write=True,
                prune=False,
            )
            print("[sync-config] 已取消删除，仅执行常规同步。")
    elif args.prune and not result.removed_paths:
        if not args.dry_run:
            # 无多余项但仍需写入常规同步结果
            sync_config_file(
                config_path=args.config,
                example_path=args.example,
                write=True,
                prune=False,
            )
            print("[sync-config] 无多余配置项需要删除，已完成常规同步。")
        else:
            print("[sync-config] 无多余配置项需要删除。")

    if args.stdout:
        print("\n--- merged config.toml ---\n")
        print(result.content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
