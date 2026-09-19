"""Skills 导入边界检查（棘轮）。

`AGENTS.md` / `skills/README.md` 规定：handler 只能依赖 Python 标准库、第三方包、
`skills/` 内部模块（含 `Undefined.skills.*` 与本目录相对导入）以及执行上下文注入
的依赖，不得直接 import `skills/` 之外的仓库模块。

历史代码里存在一批越界导入，一次性全部改完风险过高，因此这里用“棘轮”方式收敛：

- 新增越界导入会让测试失败；
- 既有越界导入记录在 `_BASELINE` 中，随重构逐步从清单里移除；
- 清单里已经不存在的条目同样会让测试失败，避免基线腐烂。

需要新增跨 skills 的公共能力时，把实现放到 `src/Undefined/skills/shared.py`
（或同类 skills 内模块），而不是直接引用 `services/`、`utils/` 等内部实现。
"""

from __future__ import annotations

import ast
from pathlib import Path

_SKILLS_ROOT = Path(__file__).resolve().parents[1] / "src" / "Undefined" / "skills"

# 既有越界导入基线：{"<相对 skills 的 handler 路径>::<被导入模块>"}
_BASELINE: frozenset[str] = frozenset(
    {
        "agents/entertainment_agent/tools/ai_draw_one/handler.py::Undefined.ai.parsing",
        "agents/entertainment_agent/tools/ai_draw_one/handler.py::Undefined.attachments",
        "agents/entertainment_agent/tools/ai_draw_one/handler.py::Undefined.config",
        "agents/entertainment_agent/tools/ai_draw_one/handler.py::Undefined.token_usage_storage",
        "agents/entertainment_agent/tools/ai_draw_one/handler.py::Undefined.utils.io",
        "agents/entertainment_agent/tools/ai_draw_one/handler.py::Undefined.utils.paths",
        "agents/entertainment_agent/tools/ai_draw_one/handler.py::Undefined.utils.request_params",
        "agents/entertainment_agent/tools/ai_draw_one/handler.py::Undefined.utils.resources",
        "agents/entertainment_agent/tools/minecraft_skin/handler.py::Undefined.attachments",
        "agents/entertainment_agent/tools/minecraft_skin/handler.py::Undefined.utils.paths",
        "agents/entertainment_agent/tools/wenchang_dijun/handler.py::Undefined.attachments",
        "agents/file_analysis_agent/handler.py::Undefined.attachments",
        "agents/file_analysis_agent/tools/cleanup_temp/handler.py::Undefined.utils.paths",
        "agents/file_analysis_agent/tools/describe_pdf_page/handler.py::Undefined.utils",
        "agents/file_analysis_agent/tools/describe_pdf_page/handler.py::Undefined.utils.paths",
        "agents/info_agent/tools/arxiv_search/handler.py::Undefined.arxiv.client",
        "agents/info_agent/tools/bilibili_search/handler.py::Undefined.bilibili.wbi",
        "agents/info_agent/tools/bilibili_search/handler.py::Undefined.bilibili.wbi_request",
        "agents/info_agent/tools/bilibili_search/handler.py::Undefined.config",
        "agents/info_agent/tools/bilibili_user_info/handler.py::Undefined.bilibili.wbi",
        "agents/info_agent/tools/bilibili_user_info/handler.py::Undefined.config",
        "agents/info_agent/tools/net_check/handler.py::Undefined.config",
        "agents/web_agent/tools/crawl_webpage/handler.py::Undefined.ai.crawl4ai_support",
        "agents/web_agent/tools/crawl_webpage/handler.py::Undefined.config",
        "commands/admin/handler.py::Undefined.services.commands.context",
        "commands/bugfix/handler.py::Undefined.services.commands.context",
        "commands/changelog/handler.py::Undefined.changelog",
        "commands/changelog/handler.py::Undefined.services.commands.context",
        "commands/copyright/handler.py::Undefined.services.commands.context",
        "commands/faq/handler.py::Undefined.services.commands.context",
        "commands/feedback/handler.py::Undefined.render",
        "commands/feedback/handler.py::Undefined.services.commands.context",
        "commands/feedback/handler.py::Undefined.utils",
        "commands/feedback/handler.py::Undefined.utils.paths",
        "commands/help/handler.py::Undefined.render",
        "commands/help/handler.py::Undefined.services.commands.catalog",
        "commands/help/handler.py::Undefined.services.commands.context",
        "commands/help/handler.py::Undefined.services.commands.registry",
        "commands/help/handler.py::Undefined.utils.paths",
        "commands/naga/handler.py::Undefined.api.naga_store",
        "commands/naga/handler.py::Undefined.services.commands.context",
        "commands/profile/handler.py::Undefined.cognitive.service.helpers",
        "commands/profile/handler.py::Undefined.render",
        "commands/profile/handler.py::Undefined.services.commands.context",
        "commands/profile/handler.py::Undefined.utils.paths",
        "commands/stats/handler.py::Undefined.services.commands.context",
        "commands/summary/handler.py::Undefined.services.commands.context",
        "commands/version/handler.py::Undefined",
        "commands/version/handler.py::Undefined.changelog",
        "commands/version/handler.py::Undefined.services.commands.context",
        "tools/arxiv_paper/handler.py::Undefined.arxiv.client",
        "tools/arxiv_paper/handler.py::Undefined.arxiv.sender",
        "tools/arxiv_paper/handler.py::Undefined.attachments",
        "tools/bilibili_video/handler.py::Undefined.attachments",
        "tools/bilibili_video/handler.py::Undefined.bilibili.downloader",
        "tools/bilibili_video/handler.py::Undefined.bilibili.parser",
        "tools/bilibili_video/handler.py::Undefined.bilibili.sender",
        "tools/changelog_query/handler.py::Undefined.changelog",
        "tools/douyin_video/handler.py::Undefined.attachments",
        "tools/douyin_video/handler.py::Undefined.douyin.client",
        "tools/douyin_video/handler.py::Undefined.douyin.downloader",
        "tools/douyin_video/handler.py::Undefined.douyin.sender",
        "tools/end/handler.py::Undefined.ai.prompts.current_input",
        "tools/end/handler.py::Undefined.context",
        "tools/end/handler.py::Undefined.end_summary_storage",
        "tools/end/handler.py::Undefined.utils.coerce",
        "tools/end/handler.py::Undefined.utils.xml",
        "tools/fetch_image_uid/handler.py::Undefined.attachments",
        "tools/get_picture/handler.py::Undefined.attachments",
        "tools/get_picture/handler.py::Undefined.config",
        "tools/get_picture/handler.py::Undefined.utils.paths",
        "toolsets/group/get_avatar/handler.py::Undefined.attachments",
        "toolsets/group/get_member_title/handler.py::Undefined.context",
        "toolsets/group_analysis/activity_trend/handler.py::Undefined.onebot",
        "toolsets/group_analysis/activity_trend/handler.py::Undefined.utils.group_metrics",
        "toolsets/group_analysis/activity_trend/handler.py::Undefined.utils.message_utils",
        "toolsets/group_analysis/activity_trend/handler.py::Undefined.utils.time_utils",
        "toolsets/group_analysis/filter_members/handler.py::Undefined.utils.group_metrics",
        "toolsets/group_analysis/filter_members/handler.py::Undefined.utils.time_utils",
        "toolsets/group_analysis/inactive_risk/handler.py::Undefined.utils.group_metrics",
        "toolsets/group_analysis/join_statistics/handler.py::Undefined.utils.member_utils",
        "toolsets/group_analysis/join_statistics/handler.py::Undefined.utils.time_utils",
        "toolsets/group_analysis/level_distribution/handler.py::Undefined.utils.group_metrics",
        "toolsets/group_analysis/member_activity/handler.py::Undefined.onebot",
        "toolsets/group_analysis/member_activity/handler.py::Undefined.utils.group_metrics",
        "toolsets/group_analysis/member_activity/handler.py::Undefined.utils.message_utils",
        "toolsets/group_analysis/member_activity/handler.py::Undefined.utils.time_utils",
        "toolsets/group_analysis/member_messages/handler.py::Undefined.utils.message_utils",
        "toolsets/group_analysis/member_messages/handler.py::Undefined.utils.time_utils",
        "toolsets/group_analysis/member_structure/handler.py::Undefined.utils.group_metrics",
        "toolsets/group_analysis/message_mix/handler.py::Undefined.onebot",
        "toolsets/group_analysis/message_mix/handler.py::Undefined.utils.group_metrics",
        "toolsets/group_analysis/message_mix/handler.py::Undefined.utils.message_utils",
        "toolsets/group_analysis/message_mix/handler.py::Undefined.utils.time_utils",
        "toolsets/group_analysis/new_member_activity/handler.py::Undefined.utils.member_utils",
        "toolsets/group_analysis/new_member_activity/handler.py::Undefined.utils.message_utils",
        "toolsets/group_analysis/new_member_activity/handler.py::Undefined.utils.time_utils",
        "toolsets/group_analysis/rank_members/handler.py::Undefined.onebot",
        "toolsets/group_analysis/rank_members/handler.py::Undefined.utils.group_metrics",
        "toolsets/group_analysis/rank_members/handler.py::Undefined.utils.message_utils",
        "toolsets/group_analysis/rank_members/handler.py::Undefined.utils.time_utils",
        "toolsets/messages/get_forward_msg/handler.py::Undefined.attachments",
        "toolsets/messages/get_forward_msg/handler.py::Undefined.attachments.forward_snapshot",
        "toolsets/messages/get_forward_msg/handler.py::Undefined.attachments.segments",
        "toolsets/messages/get_forward_msg/handler.py::Undefined.utils.xml",
        "toolsets/messages/list_emojis/handler.py::Undefined.utils.qq_emoji",
        "toolsets/messages/lookup_emoji_id/handler.py::Undefined.utils.qq_emoji",
        "toolsets/messages/react_message_emoji/handler.py::Undefined.context",
        "toolsets/messages/react_message_emoji/handler.py::Undefined.utils.qq_emoji",
        "toolsets/messages/send_message/handler.py::Undefined.attachments",
        "toolsets/messages/send_message/handler.py::Undefined.utils.message_targets",
        "toolsets/messages/send_poke/handler.py::Undefined.context",
        "toolsets/messages/send_private_message/handler.py::Undefined.attachments",
        "toolsets/messages/send_text_file/handler.py::Undefined.utils.message_turn",
        "toolsets/messages/send_text_file/handler.py::Undefined.utils.paths",
        "toolsets/messages/send_url_file/handler.py::Undefined.utils.http_download",
        "toolsets/messages/send_url_file/handler.py::Undefined.utils.message_turn",
        "toolsets/messages/send_url_file/handler.py::Undefined.utils.paths",
        "toolsets/render/render_html/handler.py::Undefined.attachments",
        "toolsets/render/render_html/handler.py::Undefined.utils.cache",
        "toolsets/render/render_html/handler.py::Undefined.utils.paths",
        "toolsets/render/render_latex/handler.py::Undefined.attachments",
        "toolsets/render/render_markdown/handler.py::Undefined.attachments",
        "toolsets/render/render_markdown/handler.py::Undefined.utils.cache",
        "toolsets/render/render_markdown/handler.py::Undefined.utils.paths",
    }
)


def _collect_violations() -> set[str]:
    violations: set[str] = set()
    for handler in sorted(_SKILLS_ROOT.rglob("handler.py")):
        tree = ast.parse(handler.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or ""]
            for name in names:
                if name == "Undefined" or (
                    name.startswith("Undefined.")
                    and not name.startswith("Undefined.skills")
                ):
                    modules.add(name)
        relative = handler.relative_to(_SKILLS_ROOT).as_posix()
        for module in sorted(modules):
            violations.add(f"{relative}::{module}")
    return violations


def test_no_new_out_of_skills_imports() -> None:
    violations = _collect_violations()
    new_violations = sorted(violations - _BASELINE)
    assert not new_violations, (
        "检测到新的 skills 越界导入（handler 不得直接依赖 skills/ 之外的仓库模块）：\n  "
        + "\n  ".join(new_violations)
        + "\n请改用 Undefined.skills.shared 或同目录相对导入；确需长期保留时说明理由后再更新基线。"
    )


def test_baseline_has_no_stale_entries() -> None:
    violations = _collect_violations()
    stale = sorted(_BASELINE - violations)
    assert not stale, (
        "以下越界导入已不存在，请从基线中移除，保持棘轮只减不增：\n  "
        + "\n  ".join(stale)
    )
