"""``config.toml`` 的最小差异写入。

部署脚本只改「服务拓扑」相关的键（协议端地址、自托管服务地址、监听地址等），
其余内容与全部注释原样保留——复用 WebUI 那套 ``apply_patch`` + ``render_toml``
+ 注释映射，不自己造 TOML 写入。

调用顺序：:func:`plan_patch` 计算差异 → 调用方确认 → :func:`apply_plan` 落盘
（落盘前先备份）。解析失败时不写任何文件。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from Undefined.deploy.state import utc_stamp_compact, write_text

BACKUP_DIR_NAME = "backup"
BACKUP_FILE_PREFIX = "config_"


@dataclass(frozen=True, slots=True)
class PatchItem:
    """一条待写入项。"""

    key: str
    value: Any
    current: Any
    about: str

    @property
    def is_change(self) -> bool:
        return bool(self.current != self.value)

    @property
    def is_conflict(self) -> bool:
        """目标键已有值且与原值不同：可能被用户手工改过，覆盖前需确认。"""
        return self.current is not None and bool(self.current != self.value)

    def describe(self) -> str:
        """单行摘要；``None`` 表示该键当前不存在。"""
        if not self.is_change:
            return f"{self.key} = {self.value!r}（已是最新）"
        if self.current is None:
            return f"{self.key} = {self.value!r}（新增）"
        return f"{self.key}: {self.current!r} -> {self.value!r}"


@dataclass(slots=True)
class PatchPlan:
    """一次 ``up`` 的完整写入计划。"""

    config_path: Path
    desired: dict[str, Any]
    about: dict[str, str] = field(default_factory=dict)

    def items(self, current: dict[str, Any]) -> tuple[PatchItem, ...]:
        """按 ``desired`` 顺序生成逐项差异。"""
        return tuple(
            PatchItem(
                key=key,
                value=value,
                current=_lookup(current, key),
                about=self.about.get(key, ""),
            )
            for key, value in self.desired.items()
        )


@dataclass(frozen=True, slots=True)
class PatchOutcome:
    """写入结果。"""

    path: Path
    written: bool
    changed_keys: tuple[str, ...]
    backup_path: Path | None
    rendered: str


class ConfigError(RuntimeError):
    """配置读取/解析失败。"""


def _lookup(data: dict[str, Any], dotted_key: str) -> Any:
    """按 dotted path 取值；任一层缺失返回 ``None``。

    显式返回 ``None`` 会与「值就是 None（TOML 无 null）」等价，不影响判断。
    """
    node: Any = data
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def load_toml(path: Path) -> dict[str, Any]:
    """读取 TOML 为字典；文件缺失返回空字典，语法错误抛 :class:`ConfigError`。"""
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} 解析失败：{exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{path} 读取失败：{exc}") from exc


def ensure_config_file(config_path: Path, example_path: Path) -> bool:
    """确保 ``config.toml`` 存在（与 WebUI 一致：从示例复制）。

    返回是否新建。示例文件也缺失时抛 :class:`ConfigError`。
    """
    if config_path.is_file():
        return False
    if not example_path.is_file():
        raise ConfigError(
            f"缺少 {config_path.name}，且找不到模板 {example_path}；请先手写一份配置"
        )
    write_text(config_path, example_path.read_text(encoding="utf-8"))
    return True


def build_comment_map(config_path: Path, example_path: Path) -> dict[str, Any]:
    """构造注释映射：以示例文件为基准，用现有配置补齐示例中缺失的注释。"""
    from Undefined.webui.utils.comment import parse_comment_map

    comments = parse_comment_map(example_path) if example_path.is_file() else {}
    if config_path.is_file():
        for key, value in parse_comment_map(config_path).items():
            existing = comments.get(key)
            if existing is None:
                comments[key] = value
            else:
                merged = dict(existing)
                merged.update(value)
                comments[key] = merged
    return comments


def render_patched(
    current: dict[str, Any], patch: dict[str, Any], comments: dict[str, Any]
) -> str:
    """按 patch 渲染出新的 ``config.toml`` 文本。"""
    from Undefined.webui.utils.toml_render import apply_patch, render_toml

    return render_toml(apply_patch(current, patch), comments=comments)


def apply_plan(
    plan: PatchPlan,
    *,
    example_path: Path,
    backup_dir: Path,
    comment_map: dict[str, Any] | None = None,
) -> PatchOutcome:
    """写盘：备份现有文件 → 原子替换。

    - 无差异时不写文件、不备份，返回 ``changed_keys=()``
    - 目标键当前值与原值不同时**照常写入**：是否覆盖由调用方在
      :meth:`PatchPlan.items` 的 ``is_conflict`` 上先做确认
    """
    current = load_toml(plan.config_path)
    items = plan.items(current)
    changes = tuple(item for item in items if item.is_change)
    if not changes:
        return PatchOutcome(
            path=plan.config_path,
            written=False,
            changed_keys=(),
            backup_path=None,
            rendered="",
        )

    patch = {item.key: item.value for item in changes}
    comments = (
        comment_map
        if comment_map is not None
        else build_comment_map(plan.config_path, example_path)
    )
    rendered = render_patched(current, patch, comments)
    # 落盘前再解析一次：渲染出的内容必须是合法 TOML，避免写坏配置。
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"渲染结果不是合法 TOML，已放弃写入：{exc}") from exc

    backup_path: Path | None = None
    if plan.config_path.is_file():
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{BACKUP_FILE_PREFIX}{utc_stamp_compact()}.toml"
        write_text(backup_path, plan.config_path.read_text(encoding="utf-8"))

    write_text(plan.config_path, rendered)
    return PatchOutcome(
        path=plan.config_path,
        written=True,
        changed_keys=tuple(item.key for item in changes),
        backup_path=backup_path,
        rendered=rendered,
    )


__all__ = [
    "BACKUP_DIR_NAME",
    "BACKUP_FILE_PREFIX",
    "ConfigError",
    "PatchItem",
    "PatchOutcome",
    "PatchPlan",
    "apply_plan",
    "build_comment_map",
    "ensure_config_file",
    "load_toml",
    "render_patched",
]
