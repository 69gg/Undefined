from __future__ import annotations

import tomllib

from Undefined.webui.utils import sync_config_text


def test_sync_config_text_preserves_values_and_adds_new_fields_with_comments() -> None:
    current = """
# custom comment should stay for unknown path
[core]
bot_qq = 123456

[custom]
flag = true
"""
    example = """
# zh: 机器人小号配置。
# en: Bot account settings.
[core]
# zh: 机器人QQ号。
# en: Bot QQ number.
bot_qq = 0
# zh: 是否处理私聊消息。
# en: Process private messages.
process_private_message = true

# zh: 模板新增小节。
# en: Newly added section from template.
[features]
# zh: 是否启用模型池。
# en: Enable model pool.
pool_enabled = false
"""

    result = sync_config_text(current, example)
    data = tomllib.loads(result.content)

    assert data["core"]["bot_qq"] == 123456
    assert data["core"]["process_private_message"] is True
    assert data["features"]["pool_enabled"] is False
    assert data["custom"]["flag"] is True
    assert "# zh: 是否处理私聊消息。" in result.content
    assert "# en: Enable model pool." in result.content
    assert result.added_paths == ["core.process_private_message", "features"]


def test_sync_config_text_preserves_multiline_string_values() -> None:
    current = '''
[models.embedding]
query_instruction = """第一行
第二行
第三行"""
'''
    example = '''
[models.embedding]
query_instruction = """默认第一行
默认第二行"""
document_instruction = """文档前缀
第二行"""
'''
    result = sync_config_text(current, example)
    parsed = tomllib.loads(result.content)
    assert (
        parsed["models"]["embedding"]["query_instruction"] == "第一行\n第二行\n第三行"
    )
    assert parsed["models"]["embedding"]["document_instruction"] == "文档前缀\n第二行"
