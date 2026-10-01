"""Skills 内部共享助手。

`skills/` 下的 handler 允许依赖本模块（以及同目录的相对导入），用于收敛那些
在每个工具里各写一份的小函数。跨 `skills/` 的公共能力应优先放到这里，而不是
在多个 handler 间复制实现。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jmcpy import Genre, SearchTarget, SortBy, SubGenre, TimeRange

    from Undefined.jm.searcher import JmListingMode


def private_access_error(
    runtime_config: Any,
    target_id: int,
    *,
    prefix: str = "发送失败：",
    access_note: str = "，已被访问控制拦截",
) -> str:
    """按访问控制拒绝原因生成统一的用户可见说明。

    读取 `runtime_config.private_access_denied_reason(target_id)`：
    - `blacklist` 表示命中 `access.blocked_private_ids`；
    - 其余情况（含 `allowlist` / 未配置）统一提示不在允许列表内。

    `prefix` / `access_note` 用于保留各工具调用点的原有文案差异
    （如表情反应没有"发送失败"语义、文件类工具不带拦截说明）。
    """
    reason_getter = getattr(runtime_config, "private_access_denied_reason", None)
    reason = reason_getter(target_id) if callable(reason_getter) else None
    if reason == "blacklist":
        return (
            f"{prefix}目标用户 {target_id} 在黑名单内"
            f"（access.blocked_private_ids）{access_note}"
        )
    return (
        f"{prefix}目标用户 {target_id} 不在允许列表内"
        f"（access.allowed_private_ids）{access_note}"
    )


def parse_positive_int(
    value: Any,
    field_name: str,
) -> tuple[int | None, str | None]:
    """解析可选正整数字段，返回 `(值, 错误说明)`。

    `None` 表示未提供（返回 `(None, None)`）；非法值返回 `(None, 错误说明)`。
    """
    if value is None:
        return None, None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, f"{field_name} 必须是整数"
    if parsed <= 0:
        return None, f"{field_name} 必须是正整数"
    return parsed, None


def jm_normalize_book_id(value: str) -> str | None:
    """把车号 / ``JM<数字>`` / 禁漫链接归一化成纯数字车号（失败返回 `None`）。"""
    from Undefined.jm.parser import normalize_jm_id

    return normalize_jm_id(value)


def jm_scope_key(context: dict[str, Any]) -> str:
    """当前会话的附件作用域：优先取上下文里已解析的 ``scope_key``。"""
    scope_key = str(context.get("scope_key") or "").strip()
    if scope_key:
        return scope_key
    from Undefined.attachments import scope_from_context

    return scope_from_context(context) or ""


async def jm_book_info_text(book_id: str, *, config: Any) -> str:
    """只取本子详情（不下载），返回可直接给用户/模型的文本。"""
    from Undefined.jm.downloader import fetch_book
    from Undefined.jm.sender import format_jm_book_info

    return format_jm_book_info(await fetch_book(book_id, config=config))


async def jm_search_text(
    query: str,
    *,
    config: Any,
    mode: JmListingMode,
    page: int,
    limit: int,
    target: SearchTarget,
    sort: SortBy,
    time_range: TimeRange,
    genre: Genre,
    sub_genre: SubGenre | None,
) -> str:
    """查询禁漫本子列表（搜索 / 浏览 / 排行），返回可直接给用户/模型的文本。"""
    from Undefined.jm.searcher import describe_query, fetch_listing, format_listing

    listing = await fetch_listing(
        config=config,
        mode=mode,
        query=query,
        page=page,
        target=target,
        sort=sort,
        time_range=time_range,
        genre=genre,
        sub_genre=sub_genre,
    )
    heading = describe_query(
        mode=mode,
        query=query,
        target=target,
        sort=sort,
        time_range=time_range,
        genre=genre,
        sub_genre=sub_genre,
    )
    return format_listing(listing, heading=heading, limit=limit)


async def jm_book_attachment_text(
    book_id: str,
    *,
    registry: Any,
    scope_key: str,
    config: Any,
) -> str:
    """下载整本并注册为未加密 PDF 附件 UID，返回概要文本。"""
    from Undefined.jm.sender import fetch_jm_book_attachment

    return await fetch_jm_book_attachment(
        book_id=book_id,
        attachment_registry=registry,
        scope_key=scope_key,
        config=config,
    )


async def jm_send_book(
    book_id: str,
    *,
    sender: Any,
    target_type: str,
    target_id: int,
    config: Any,
) -> str:
    """下载整本，发送「信息 / 密码」合并转发并单独发送加密 PDF 文件。"""
    from Undefined.jm.sender import send_jm_book as _send_jm_book

    return await _send_jm_book(
        book_id,
        sender=sender,
        target_type=target_type,  # type: ignore[arg-type]
        target_id=target_id,
        config=config,
    )


__all__ = [
    "jm_book_attachment_text",
    "jm_book_info_text",
    "jm_normalize_book_id",
    "jm_scope_key",
    "jm_search_text",
    "jm_send_book",
    "parse_positive_int",
    "private_access_error",
]
