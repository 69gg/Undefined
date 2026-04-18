from __future__ import annotations

from typing import Any


from Undefined.skills.toolsets.messages.get_recent_messages.handler import (
    _format_message_xml,
)


def test_format_message_xml_group_with_all_attributes() -> None:
    """测试群消息包含 role/title/level 时 XML 全部显示"""
    msg: dict[str, Any] = {
        "type": "group",
        "display_name": "测试用户",
        "user_id": "10001",
        "chat_id": "20001",
        "chat_name": "测试群",
        "timestamp": "2026-04-11 10:00:00",
        "message": "测试消息",
        "message_id": 123456,
        "role": "admin",
        "title": "管理员",
        "level": "Lv.10",
    }

    result = _format_message_xml(msg)

    assert 'role="admin"' in result
    assert 'title="管理员"' in result
    assert 'level="Lv.10"' in result
    assert 'message_id="123456"' in result
    assert "<content>测试消息</content>" in result


def test_format_message_xml_group_with_empty_level() -> None:
    """测试群消息 level 为空时 XML 不包含 level 属性"""
    msg: dict[str, Any] = {
        "type": "group",
        "display_name": "测试用户",
        "user_id": "10001",
        "chat_id": "20001",
        "chat_name": "测试群",
        "timestamp": "2026-04-11 10:00:00",
        "message": "测试消息",
        "role": "member",
        "title": "",
        "level": "",
    }

    result = _format_message_xml(msg)

    assert "level=" not in result
    assert 'role="member"' in result
    assert "title=" not in result


def test_format_message_xml_private_without_level() -> None:
    """测试私聊消息不包含 role/title/level 属性"""
    msg: dict[str, Any] = {
        "type": "private",
        "display_name": "测试用户",
        "user_id": "10001",
        "chat_id": "10001",
        "chat_name": "QQ用户10001",
        "timestamp": "2026-04-11 10:00:00",
        "message": "私聊消息",
    }

    result = _format_message_xml(msg)

    assert "role=" not in result
    assert "title=" not in result
    assert "level=" not in result
    assert "<content>私聊消息</content>" in result


def test_format_message_xml_group_with_only_level() -> None:
    """测试群消息只设置 level 时仅显示 level 属性"""
    msg: dict[str, Any] = {
        "type": "group",
        "display_name": "测试用户",
        "user_id": "10001",
        "chat_id": "20001",
        "chat_name": "测试群",
        "timestamp": "2026-04-11 10:00:00",
        "message": "测试消息",
        "role": "",
        "title": "",
        "level": "Lv.5",
    }

    result = _format_message_xml(msg)

    assert 'level="Lv.5"' in result
    assert "role=" not in result
    assert "title=" not in result


def test_format_message_xml_group_without_level_key() -> None:
    """测试群消息没有 level 键时不显示 level 属性"""
    msg: dict[str, Any] = {
        "type": "group",
        "display_name": "测试用户",
        "user_id": "10001",
        "chat_id": "20001",
        "chat_name": "测试群",
        "timestamp": "2026-04-11 10:00:00",
        "message": "测试消息",
        "role": "member",
        "title": "",
    }

    result = _format_message_xml(msg)

    assert "level=" not in result
    assert 'role="member"' in result


def test_format_message_xml_group_with_role_and_title() -> None:
    """测试群消息有 role 和 title 但无 level"""
    msg: dict[str, Any] = {
        "type": "group",
        "display_name": "测试用户",
        "user_id": "10001",
        "chat_id": "20001",
        "chat_name": "测试群",
        "timestamp": "2026-04-11 10:00:00",
        "message": "测试消息",
        "role": "admin",
        "title": "群主",
        "level": "",
    }

    result = _format_message_xml(msg)

    assert 'role="admin"' in result
    assert 'title="群主"' in result
    assert "level=" not in result


def test_format_message_xml_private_with_level_ignored() -> None:
    """测试私聊消息即使有 level 也不显示"""
    msg: dict[str, Any] = {
        "type": "private",
        "display_name": "测试用户",
        "user_id": "10001",
        "chat_id": "10001",
        "chat_name": "QQ用户10001",
        "timestamp": "2026-04-11 10:00:00",
        "message": "私聊消息",
        "role": "member",
        "title": "测试",
        "level": "Lv.99",
    }

    result = _format_message_xml(msg)

    assert "role=" not in result
    assert "title=" not in result
    assert "level=" not in result
