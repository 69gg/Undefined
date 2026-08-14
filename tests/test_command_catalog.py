from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from Undefined.ai.prompts import PromptBuilder
from Undefined.end_summary_storage import EndSummaryRecord
from Undefined.services.commands.catalog import CommandCatalog
from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandRegistry
from Undefined.skills.toolsets.commands.get.handler import (
    execute as commands_get_execute,
)
from Undefined.skills.toolsets.commands.search.handler import (
    execute as commands_search_execute,
)


class _FakeConfig:
    def __init__(self, *, admins: set[int], superadmins: set[int]) -> None:
        self._admins = admins
        self._superadmins = superadmins

    def is_admin(self, sender_id: int) -> bool:
        return int(sender_id) in self._admins or int(sender_id) in self._superadmins

    def is_superadmin(self, sender_id: int) -> bool:
        return int(sender_id) in self._superadmins


class _FakeEndSummaryStorage:
    async def load(self) -> list[EndSummaryRecord]:
        return []


PUBLIC_USER = 10001
ADMIN_USER = 20001
SUPERADMIN_USER = 30001


def _write_command(
    base_dir: Path,
    command_dir_name: str,
    *,
    command_name: str,
    description: str = "测试命令",
    usage: str | None = None,
    example: str | None = None,
    aliases: list[str] | None = None,
    permission: str = "public",
    allow_in_private: bool = True,
    show_in_help: bool = True,
    order: int = 10,
    rate_limit: dict[str, int] | None = None,
    subcommands: dict[str, Any] | None = None,
    doc_text: str | None = None,
    visibility_text: str | None = None,
) -> Path:
    command_dir = base_dir / command_dir_name
    command_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "name": command_name,
        "description": description,
        "usage": usage or f"/{command_name}",
        "example": example or f"/{command_name}",
        "permission": permission,
        "allow_in_private": allow_in_private,
        "rate_limit": rate_limit or {"user": 10, "admin": 5, "superadmin": 0},
        "show_in_help": show_in_help,
        "order": order,
        "aliases": aliases or [],
    }
    if subcommands is not None:
        payload["subcommands"] = subcommands
    (command_dir / "config.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (command_dir / "handler.py").write_text(
        "from __future__ import annotations\n\n"
        "from Undefined.services.commands.context import CommandContext\n\n"
        "async def execute(args: list[str], context: CommandContext) -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )
    if doc_text is not None:
        (command_dir / "README.md").write_text(doc_text, encoding="utf-8")
    if visibility_text is not None:
        (command_dir / "policy.py").write_text(visibility_text, encoding="utf-8")
    return command_dir


def _seed_commands(base_dir: Path) -> None:
    _write_command(
        base_dir,
        "help",
        command_name="help",
        description="显示命令列表或详细帮助",
        aliases=["h"],
        order=1,
        doc_text="# Help 文档\n\n这是公开帮助。",
    )
    _write_command(
        base_dir,
        "profile",
        command_name="profile",
        description="查看认知侧写",
        aliases=["p"],
        order=2,
        allow_in_private=True,
        subcommands={"show": {"description": "查看侧写", "args": "[QQ]"}},
        doc_text="# Profile 文档\n\n查看用户或群侧写。",
    )
    _write_command(
        base_dir,
        "grouponly",
        command_name="grouponly",
        description="仅群聊可用的命令",
        allow_in_private=False,
        order=3,
        doc_text="群聊专属文档，含限流说明。",
    )
    _write_command(
        base_dir,
        "admincmd",
        command_name="admincmd",
        description="管理员维护命令",
        aliases=["ac"],
        permission="admin",
        order=4,
        rate_limit={"user": 60, "admin": 10, "superadmin": 0},
        doc_text="管理员机密文档，禁止泄露。",
    )
    _write_command(
        base_dir,
        "super",
        command_name="super",
        description="超管专属命令",
        permission="superadmin",
        order=5,
        doc_text="超管机密文档。",
    )
    _write_command(
        base_dir,
        "hidden",
        command_name="hidden",
        description="不在帮助中展示",
        show_in_help=False,
        order=6,
        doc_text="隐藏命令文档。",
    )
    _write_command(
        base_dir,
        "gated",
        command_name="gated",
        description="策略隐藏命令",
        order=7,
        visibility_text=(
            "from __future__ import annotations\n\n"
            "from Undefined.services.commands.context import CommandContext\n\n"
            "def is_command_visible(context: CommandContext) -> bool:\n"
            "    return False\n"
        ),
        doc_text="策略隐藏文档。",
    )


def _make_catalog(tmp_path: Path) -> CommandCatalog:
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir(parents=True)
    _seed_commands(commands_dir)
    registry = CommandRegistry(commands_dir)
    registry.load_commands()
    config = _FakeConfig(admins={ADMIN_USER}, superadmins={SUPERADMIN_USER})
    return CommandCatalog(registry, config)


def _viewer(
    catalog: CommandCatalog,
    *,
    sender_id: int,
    scope: str,
    group_id: int = 10001,
) -> CommandContext:
    return catalog.viewer_from_mapping(
        {
            "sender_id": sender_id,
            "user_id": sender_id,
            "request_type": scope,
            "group_id": 0 if scope == "private" else group_id,
            "is_private_chat": scope == "private",
        }
    )


def test_catalog_filters_by_permission_and_private_scope(tmp_path: Path) -> None:
    catalog = _make_catalog(tmp_path)
    public_group = _viewer(catalog, sender_id=PUBLIC_USER, scope="group")
    public_private = _viewer(catalog, sender_id=PUBLIC_USER, scope="private")
    admin_group = _viewer(catalog, sender_id=ADMIN_USER, scope="group")
    super_group = _viewer(catalog, sender_id=SUPERADMIN_USER, scope="group")

    public_names = {item.name for item in catalog.list_visible(public_group)}
    assert public_names == {"help", "profile", "grouponly"}

    private_names = {item.name for item in catalog.list_visible(public_private)}
    assert private_names == {"help", "profile"}
    assert "grouponly" not in private_names

    admin_names = {item.name for item in catalog.list_visible(admin_group)}
    assert "admincmd" in admin_names
    assert "super" not in admin_names
    assert "hidden" not in admin_names
    assert "gated" not in admin_names

    super_names = {item.name for item in catalog.list_visible(super_group)}
    assert {"help", "profile", "grouponly", "admincmd", "super"} <= super_names
    assert "hidden" not in super_names
    assert "gated" not in super_names


def test_catalog_search_ranks_name_alias_description_then_doc(tmp_path: Path) -> None:
    catalog = _make_catalog(tmp_path)
    viewer = _viewer(catalog, sender_id=PUBLIC_USER, scope="group")

    by_name = catalog.search(viewer, "profile")
    assert [item.name for item in by_name] == ["profile"]

    by_alias = catalog.search(viewer, "h")
    assert by_alias[0].name == "help"

    by_desc = catalog.search(viewer, "认知侧写")
    assert [item.name for item in by_desc] == ["profile"]

    by_doc = catalog.search(viewer, "公开帮助")
    assert [item.name for item in by_doc] == ["help"]

    public_search = catalog.search(viewer, "机密")
    assert public_search == []
    all_secret = {item.name for item in catalog.search_all("机密")}
    assert all_secret == {"admincmd", "super"}


def test_catalog_get_hides_unauthorized_docs(tmp_path: Path) -> None:
    catalog = _make_catalog(tmp_path)
    public_viewer = _viewer(catalog, sender_id=PUBLIC_USER, scope="group")
    admin_viewer = _viewer(catalog, sender_id=ADMIN_USER, scope="group")

    assert catalog.get(public_viewer, "/p") is not None
    assert catalog.get(public_viewer, "admincmd") is None
    assert catalog.get_any("admincmd") is not None
    assert catalog.get(public_viewer, "missing") is None
    assert catalog.get_any("missing") is None

    admin_meta = catalog.get(admin_viewer, "ac")
    assert admin_meta is not None
    detail = catalog.format_detail(admin_meta)
    assert "管理员机密文档，禁止泄露。" in detail
    assert "限流：普通60s / 管理员10s / 超管无限制" in detail
    assert "权限：管理员" in detail


@pytest.mark.asyncio
async def test_commands_search_and_get_tools_query_all_commands(
    tmp_path: Path,
) -> None:
    catalog = _make_catalog(tmp_path)
    public_context: dict[str, Any] = {
        "command_catalog": catalog,
        "sender_id": PUBLIC_USER,
        "request_type": "group",
        "group_id": 10001,
    }

    empty = await commands_search_execute({"query": ""}, public_context)
    assert empty == "请提供查询关键词"

    listed = await commands_search_execute({"query": "机密"}, public_context)
    assert "/admincmd(/ac)" in listed
    assert "权限：管理员" in listed

    missing = await commands_get_execute({"name": "nope"}, public_context)
    assert missing == "未找到命令"

    admin_detail = await commands_get_execute({"name": "admincmd"}, public_context)
    assert "管理员机密文档，禁止泄露。" in admin_detail
    assert "权限：管理员" in admin_detail

    allowed = await commands_get_execute({"name": "/p"}, public_context)
    assert "/profile(/p)" in allowed
    assert "查看用户或群侧写。" in allowed
    assert "子命令：" in allowed


@pytest.mark.asyncio
async def test_commands_tools_filter_by_optional_group_and_user(
    tmp_path: Path,
) -> None:
    catalog = _make_catalog(tmp_path)
    public_context: dict[str, Any] = {
        "command_catalog": catalog,
        "sender_id": PUBLIC_USER,
        "request_type": "group",
        "group_id": 10001,
    }

    assert catalog.viewer_for_tool_args({}) is None
    assert catalog.viewer_for_tool_args({"query": "help"}) is None

    group_only = catalog.viewer_for_tool_args({"group_id": "10001"})
    assert group_only is not None
    assert group_only.scope == "group"
    assert group_only.group_id == 10001
    assert group_only.sender_id == 0

    user_only = catalog.viewer_for_tool_args({"user_id": str(ADMIN_USER)})
    assert user_only is not None
    assert user_only.scope == "private"
    assert user_only.sender_id == ADMIN_USER

    both = catalog.viewer_for_tool_args({"group_id": 10001, "qq": PUBLIC_USER})
    assert both is not None
    assert both.scope == "group"
    assert both.sender_id == PUBLIC_USER

    public_group = await commands_search_execute(
        {"query": "命令", "group_id": 10001, "user_id": PUBLIC_USER},
        public_context,
    )
    assert "视角：会话：群聊 10001 | 用户：10001 | 权限：普通用户" in public_group
    assert "/help(/h)" in public_group
    assert "grouponly" in public_group
    assert "admincmd" not in public_group

    public_private = await commands_search_execute(
        {"query": "命令", "user_id": PUBLIC_USER},
        public_context,
    )
    assert "视角：会话：私聊 | 用户：10001 | 权限：普通用户" in public_private
    assert "grouponly" not in public_private
    assert "/help(/h)" in public_private

    admin_group = await commands_search_execute(
        {"query": "机密", "group_id": 10001, "user_id": ADMIN_USER},
        public_context,
    )
    assert "/admincmd(/ac)" in admin_group
    assert "super" not in admin_group

    denied = await commands_get_execute(
        {"name": "admincmd", "group_id": 10001, "user_id": PUBLIC_USER},
        public_context,
    )
    assert "该视角无权使用该命令。" in denied
    assert "管理员机密文档，禁止泄露。" in denied
    assert "会话：群聊 10001" in denied

    allowed = await commands_get_execute(
        {"name": "grouponly", "group_id": 10001, "user_id": PUBLIC_USER},
        public_context,
    )
    assert "该视角可以使用该命令。" in allowed
    assert "仅群聊可用的命令" in allowed


def test_format_prompt_block_lists_visible_commands_only(tmp_path: Path) -> None:
    catalog = _make_catalog(tmp_path)
    public_block = catalog.format_prompt_block(
        _viewer(catalog, sender_id=PUBLIC_USER, scope="group")
    )
    assert "【当前发送者可用斜杠命令】" in public_block
    assert "会话：群聊 | 权限：普通用户" in public_block
    assert "/help(/h) — 显示命令列表或详细帮助" in public_block
    assert "/profile(/p) — 查看认知侧写（1个子命令）" in public_block
    assert "admincmd" not in public_block
    assert "不要代替用户发送斜杠命令。" in public_block
    assert "不是完整命令目录" in public_block
    assert "查询全部命令" in public_block

    admin_block = catalog.format_prompt_block(
        _viewer(catalog, sender_id=ADMIN_USER, scope="private")
    )
    assert "会话：私聊 | 权限：管理员" in admin_block
    assert "/admincmd(/ac)" in admin_block
    assert "grouponly" not in admin_block


def _make_prompt_builder(config: Any) -> PromptBuilder:
    return PromptBuilder(
        bot_qq=123456,
        memory_storage=None,
        end_summary_storage=cast(Any, _FakeEndSummaryStorage()),
        runtime_config_getter=lambda: config,
        anthropic_skill_registry=None,
        cognitive_service=None,
    )


def test_prompt_builder_skips_commands_block_without_registry(
    tmp_path: Path,
) -> None:
    catalog = _make_catalog(tmp_path)
    builder = _make_prompt_builder(catalog.config)
    prompt = builder._build_available_commands_prompt(
        {
            "sender_id": PUBLIC_USER,
            "group_id": 10001,
            "request_type": "group",
        }
    )
    assert prompt == ""


def test_prompt_builder_injects_available_commands_block(tmp_path: Path) -> None:
    catalog = _make_catalog(tmp_path)
    builder = _make_prompt_builder(catalog.config)
    builder.set_command_registry(catalog.registry)
    prompt = builder._build_available_commands_prompt(
        {
            "sender_id": PUBLIC_USER,
            "group_id": 10001,
            "request_type": "group",
        }
    )
    assert "【当前发送者可用斜杠命令】" in prompt
    assert "/help(/h)" in prompt
    assert "admincmd" not in prompt


@pytest.mark.asyncio
async def test_build_messages_injects_commands_before_current_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _make_catalog(tmp_path)
    builder = _make_prompt_builder(catalog.config)
    builder.set_command_registry(catalog.registry)

    async def _fake_load_system_prompt(*, nagaagent_active: bool | None = None) -> str:
        return "系统提示词"

    async def _fake_load_each_rules() -> str:
        return "每次都要先检查缓存"

    monkeypatch.setattr(builder, "_load_system_prompt", _fake_load_system_prompt)
    monkeypatch.setattr(builder, "_load_each_rules", _fake_load_each_rules)

    async def _fake_recent_messages(
        chat_id: str, msg_type: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        _ = chat_id, msg_type, start, end
        return []

    messages = await builder.build_messages(
        '<message sender="测试用户" sender_id="10001" group_id="10001" '
        'time="2026-04-03 10:02:00">\n<content>有哪些命令？</content>\n</message>',
        get_recent_messages_callback=_fake_recent_messages,
        extra_context={
            "group_id": 10001,
            "sender_id": PUBLIC_USER,
            "sender_name": "测试用户",
            "request_type": "group",
        },
    )
    contents = [str(message.get("content", "")) for message in messages]
    commands_idx = next(
        idx
        for idx, content in enumerate(contents)
        if "【当前发送者可用斜杠命令】" in content
    )
    time_idx = next(
        idx for idx, content in enumerate(contents) if "【当前时间】" in content
    )
    assert commands_idx < time_idx
    assert "/help(/h)" in contents[commands_idx]
