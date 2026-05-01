"""GitHub 仓库卡片渲染与发送。"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal
import uuid

from Undefined.github.client import get_public_repo_info
from Undefined.github.models import GitHubRepoInfo
from Undefined.render import render_html_to_image
from Undefined.utils.paths import RENDER_CACHE_DIR, ensure_dir

if TYPE_CHECKING:
    from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)


def _html_text(text: str) -> str:
    return html.escape(text, quote=True)


def _format_count(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,}"


def _date(value: str) -> str:
    return value[:10] if value else "-"


def _stat_item(label: str, value: int | None) -> str:
    return (
        '<div class="stat">'
        f'<div class="stat-value">{_html_text(_format_count(value))}</div>'
        f'<div class="stat-label">{_html_text(label)}</div>'
        "</div>"
    )


def _chip(label: str, value: str) -> str:
    if not value:
        value = "-"
    return (
        '<div class="chip">'
        f"<span>{_html_text(label)}</span>"
        f"<strong>{_html_text(value)}</strong>"
        "</div>"
    )


def _status_badges(info: GitHubRepoInfo) -> str:
    badges: list[str] = ['<span class="badge public">Public</span>']
    if info.archived:
        badges.append('<span class="badge muted">Archived</span>')
    if info.fork:
        badges.append('<span class="badge muted">Fork</span>')
    return "".join(badges)


def _topic_html(info: GitHubRepoInfo) -> str:
    topics = info.topics[:6]
    if not topics:
        return ""
    topic_items = "".join(f"<span>{_html_text(topic)}</span>" for topic in topics)
    return f'<div class="topics">{topic_items}</div>'


def _build_repo_card_html(info: GitHubRepoInfo) -> str:
    description = info.description or "No description provided."
    avatar = info.owner_avatar_url
    avatar_html = (
        f'<img class="avatar" src="{_html_text(avatar)}" alt="">'
        if avatar
        else '<div class="avatar placeholder"></div>'
    )
    stats = "".join(
        [
            _stat_item("Stars", info.stars),
            _stat_item("Forks", info.forks),
            _stat_item("Issues", info.open_issues),
            _stat_item("Contributors", info.contributors),
            _stat_item("Watchers", info.watchers),
        ]
    )
    chips = "".join(
        [
            _chip("Language", info.language),
            _chip("License", info.license_name),
            _chip("Branch", info.default_branch),
            _chip("Updated", _date(info.updated_at)),
        ]
    )
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            padding: 24px;
            background: #f3f4f6;
            color: #111827;
            font-family: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', Arial, sans-serif;
        }}
        .card {{
            width: 720px;
            margin: 0 auto;
            border: 1px solid #d8dee4;
            border-radius: 8px;
            background: #ffffff;
            overflow: hidden;
            box-shadow: 0 12px 28px rgba(15, 23, 42, 0.10);
        }}
        .top {{
            display: flex;
            gap: 16px;
            align-items: center;
            padding: 22px 24px 18px;
            border-bottom: 1px solid #e5e7eb;
            background: #fafbfc;
        }}
        .avatar {{
            width: 76px;
            height: 76px;
            border-radius: 8px;
            border: 1px solid #d0d7de;
            background: #e5e7eb;
            object-fit: cover;
            flex: 0 0 auto;
        }}
        .placeholder {{ background: linear-gradient(135deg, #111827, #4b5563); }}
        .title-block {{ min-width: 0; flex: 1; }}
        .eyebrow {{
            margin: 0 0 5px;
            color: #57606a;
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0;
        }}
        h1 {{
            margin: 0;
            color: #0969da;
            font-size: 28px;
            line-height: 1.22;
            font-weight: 800;
            overflow-wrap: anywhere;
        }}
        .badges {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 9px; }}
        .badge {{
            display: inline-flex;
            align-items: center;
            min-height: 22px;
            padding: 2px 8px;
            border-radius: 5px;
            font-size: 12px;
            font-weight: 800;
        }}
        .public {{ color: #116329; background: #dafbe1; border: 1px solid #aceebb; }}
        .muted {{ color: #57606a; background: #f6f8fa; border: 1px solid #d0d7de; }}
        .body {{ padding: 20px 24px 24px; }}
        .description {{
            margin: 0 0 18px;
            color: #374151;
            font-size: 16px;
            line-height: 1.6;
            overflow-wrap: anywhere;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 8px;
            margin-bottom: 14px;
        }}
        .stat {{
            min-width: 0;
            border: 1px solid #e5e7eb;
            border-radius: 6px;
            padding: 10px 8px;
            background: #ffffff;
            text-align: center;
        }}
        .stat-value {{
            color: #111827;
            font-size: 20px;
            line-height: 1.1;
            font-weight: 800;
            overflow-wrap: anywhere;
        }}
        .stat-label {{
            margin-top: 4px;
            color: #6b7280;
            font-size: 12px;
            font-weight: 700;
        }}
        .chips {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }}
        .chip {{
            min-width: 0;
            border: 1px solid #e5e7eb;
            border-radius: 6px;
            padding: 9px 10px;
            background: #f9fafb;
        }}
        .chip span {{ display: block; color: #6b7280; font-size: 12px; font-weight: 700; }}
        .chip strong {{
            display: block;
            margin-top: 2px;
            color: #111827;
            font-size: 14px;
            line-height: 1.35;
            overflow-wrap: anywhere;
        }}
        .topics {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 14px; }}
        .topics span {{
            padding: 3px 8px;
            border: 1px solid #bfdbfe;
            border-radius: 5px;
            background: #eff6ff;
            color: #1d4ed8;
            font-size: 12px;
            font-weight: 700;
        }}
        .footer {{
            margin-top: 16px;
            padding-top: 13px;
            border-top: 1px solid #e5e7eb;
            color: #57606a;
            font-size: 13px;
            overflow-wrap: anywhere;
        }}
    </style>
</head>
<body>
    <main class="card">
        <section class="top">
            {avatar_html}
            <div class="title-block">
                <p class="eyebrow">GitHub Repository</p>
                <h1>{_html_text(info.full_name or info.repo_id)}</h1>
                <div class="badges">{_status_badges(info)}</div>
            </div>
        </section>
        <section class="body">
            <p class="description">{_html_text(description)}</p>
            <div class="stats">{stats}</div>
            <div class="chips">{chips}</div>
            {_topic_html(info)}
            <div class="footer">{_html_text(info.html_url)}</div>
        </section>
    </main>
</body>
</html>"""


def _build_fallback_message(info: GitHubRepoInfo) -> str:
    lines = [
        f"GitHub: {info.full_name or info.repo_id}",
        info.description or "No description provided.",
        (
            f"Stars: {_format_count(info.stars)} | Forks: {_format_count(info.forks)} | "
            f"Issues: {_format_count(info.open_issues)} | Contributors: {_format_count(info.contributors)}"
        ),
    ]
    if info.language or info.license_name:
        lines.append(
            f"Language: {info.language or '-'} | License: {info.license_name or '-'}"
        )
    if info.html_url:
        lines.append(info.html_url)
    return "\n".join(lines)


async def _render_repo_card(info: GitHubRepoInfo, output_path: Path) -> None:
    html_content = _build_repo_card_html(info)
    await render_html_to_image(
        html_content,
        str(output_path),
        viewport_width=768,
        screenshot_selector=".card",
    )


async def _send_message(
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    message: str,
    *,
    history_message: str | None = None,
) -> None:
    if target_type == "group":
        await sender.send_group_message(
            target_id,
            message,
            history_message=history_message,
        )
    else:
        await sender.send_private_message(
            target_id,
            message,
            history_message=history_message,
        )


async def send_github_repo_card(
    *,
    repo_id: str,
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    request_timeout: float = 10.0,
    context: dict[str, object] | None = None,
) -> str:
    """获取 public 仓库信息并发送图片卡片。"""
    info = await get_public_repo_info(
        repo_id,
        request_timeout=request_timeout,
        context=context,
    )
    output_dir = ensure_dir(RENDER_CACHE_DIR / "github")
    output_path = (
        output_dir
        / f"github_{info.repo_id.replace('/', '_')}_{uuid.uuid4().hex[:8]}.png"
    )

    try:
        await _render_repo_card(info, output_path)
        message = f"[CQ:image,file={output_path.resolve().as_uri()}]"
    except Exception:
        logger.exception("[GitHub] 渲染仓库卡片失败，回退到文本: repo=%s", info.repo_id)
        message = _build_fallback_message(info)

    await _send_message(
        sender,
        target_type,
        target_id,
        message,
        history_message=_build_fallback_message(info),
    )
    return f"已发送 GitHub 仓库卡片: {info.repo_id}"
