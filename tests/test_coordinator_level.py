from __future__ import annotations

from unittest.mock import MagicMock


from Undefined.services.ai_coordinator import AICoordinator


def _make_coordinator() -> AICoordinator:
    """创建用于测试的 AICoordinator 实例"""
    config = MagicMock()
    ai = MagicMock()
    queue_manager = MagicMock()
    history_manager = MagicMock()
    sender = MagicMock()
    onebot = MagicMock()
    scheduler = MagicMock()
    security = MagicMock()

    coordinator = AICoordinator(
        config=config,
        ai=ai,
        queue_manager=queue_manager,
        history_manager=history_manager,
        sender=sender,
        onebot=onebot,
        scheduler=scheduler,
        security=security,
    )

    return coordinator


def test_build_prompt_with_level_includes_level_attribute() -> None:
    """测试 _build_prompt 带 level 参数时 XML 包含 level 属性"""
    coordinator = _make_coordinator()

    result = coordinator._build_prompt(
        prefix="",
        name="测试用户",
        uid=10001,
        gid=20001,
        gname="测试群",
        loc="测试群",
        role="member",
        title="",
        time_str="2026-04-11 10:00:00",
        text="测试消息",
        attachments=None,
        message_id=123456,
        level="Lv.5",
    )

    assert 'level="Lv.5"' in result
    assert "<message" in result
    assert 'message_id="123456"' in result


def test_build_prompt_with_empty_level_excludes_level_attribute() -> None:
    """测试 _build_prompt level 为空字符串时 XML 不包含 level 属性"""
    coordinator = _make_coordinator()

    result = coordinator._build_prompt(
        prefix="",
        name="测试用户",
        uid=10001,
        gid=20001,
        gname="测试群",
        loc="测试群",
        role="member",
        title="",
        time_str="2026-04-11 10:00:00",
        text="测试消息",
        level="",
    )

    assert "level=" not in result
    assert "<message" in result


def test_build_prompt_without_level_excludes_level_attribute() -> None:
    """测试 _build_prompt 不传 level 参数时 XML 不包含 level 属性"""
    coordinator = _make_coordinator()

    result = coordinator._build_prompt(
        prefix="",
        name="测试用户",
        uid=10001,
        gid=20001,
        gname="测试群",
        loc="测试群",
        role="member",
        title="",
        time_str="2026-04-11 10:00:00",
        text="测试消息",
    )

    assert "level=" not in result
    assert "<message" in result


def test_build_prompt_with_special_chars_in_level() -> None:
    """测试 _build_prompt level 包含特殊字符时能正确转义"""
    coordinator = _make_coordinator()

    result = coordinator._build_prompt(
        prefix="",
        name="测试用户",
        uid=10001,
        gid=20001,
        gname="测试群",
        loc="测试群",
        role="member",
        title="",
        time_str="2026-04-11 10:00:00",
        text="测试消息",
        level='Lv.5 <test&"attr">',
    )

    assert "level=" in result
    assert '<test&"attr">' not in result
    assert "&lt;" in result or "&amp;" in result or "&quot;" in result


def test_build_prompt_with_all_attributes() -> None:
    """测试 _build_prompt 包含所有属性时的输出"""
    coordinator = _make_coordinator()

    result = coordinator._build_prompt(
        prefix="系统提示:\n",
        name="测试用户",
        uid=10001,
        gid=20001,
        gname="测试群",
        loc="测试群",
        role="admin",
        title="管理员",
        time_str="2026-04-11 10:00:00",
        text="测试消息内容",
        attachments=[{"uid": "pic_001", "kind": "image"}],
        message_id=123456,
        level="Lv.10",
    )

    assert "系统提示:\n" in result
    assert 'sender="测试用户"' in result
    assert 'sender_id="10001"' in result
    assert 'group_id="20001"' in result
    assert 'group_name="测试群"' in result
    assert 'role="admin"' in result
    assert 'title="管理员"' in result
    assert 'level="Lv.10"' in result
    assert 'message_id="123456"' in result
    assert "<content>测试消息内容</content>" in result
    assert "<attachments>" in result
