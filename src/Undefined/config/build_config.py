"""Build Config from parsed TOML mapping."""

from __future__ import annotations


from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .config_class import Config

from .load_sections import (
    load_access,
    load_core,
    load_domains,
    load_finalize,
    load_history_skills,
    load_integrations,
    load_knowledge,
    load_logging_tools,
    load_models,
    load_network,
)


# 从中间态构建最终对象
def build_config(
    data: dict[str, Any],
    *,
    strict: bool = True,
    config_path: Optional[Path] = None,
) -> "Config":
    """从已解析的 TOML mapping 构建 Config。"""
    from .config_class import Config

    # 按依赖顺序分阶段加载：core/knowledge/models 在前，access 等依赖 admin 合并
    ctx: dict[str, Any] = {}
    ctx.update(load_core(data))
    ctx.update(load_knowledge(data))
    ctx.update(load_models(data))
    from .parsers import _merge_admins

    # 合并 config.toml 与本地 admins.json，超管始终纳入 admin 列表
    superadmin_qq, admin_qqs = _merge_admins(
        superadmin_qq=ctx["superadmin_qq"], admin_qqs=ctx["admin_qqs"]
    )
    ctx["superadmin_qq"] = superadmin_qq
    ctx["admin_qqs"] = admin_qqs
    ctx.update(load_access(data))
    ctx.update(load_logging_tools(data))
    ctx.update(load_history_skills(data))
    ctx.update(load_network(data))
    ctx.update(load_integrations(data))
    # domains 含 WebUI/API/认知/合并器等子域，放最后以便前面模型段已就绪
    ctx.update(load_domains(data, config_path=config_path))
    load_finalize(ctx, strict=strict)  # strict 时校验必填项并打 debug 摘要
    return Config(**ctx)
