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


def test_sync_config_text_merges_new_fields_into_existing_pool_model_entries() -> None:
    current = """
[models.chat]
api_url = "https://primary.example/v1"
api_key = "primary-key"
model_name = "primary-model"
max_tokens = 4096

[models.chat.pool]
enabled = true
strategy = "round_robin"

[[models.chat.pool.models]]
model_name = "pool-a"
api_url = "https://pool.example/v1"
api_key = "pool-key"
max_tokens = 2048
"""
    example = """
[models.chat]
api_url = ""
api_key = ""
model_name = ""
max_tokens = 4096
api_mode = "responses"
responses_tool_choice_compat = true
responses_force_stateless_replay = true

[models.chat.request_params]
temperature = 0.2

[models.chat.pool]
enabled = false
strategy = "default"
models = []
"""

    result = sync_config_text(current, example)
    parsed = tomllib.loads(result.content)
    model = parsed["models"]["chat"]["pool"]["models"][0]

    assert model["model_name"] == "pool-a"
    assert model["api_mode"] == "responses"
    assert model["responses_tool_choice_compat"] is True
    assert model["responses_force_stateless_replay"] is True
    assert model["request_params"]["temperature"] == 0.2
    assert "models.chat.pool.models[0].api_mode" in result.added_paths
    assert "models.chat.pool.models[0].request_params" in result.added_paths


def test_sync_config_text_prune_preserves_passthrough_request_params() -> None:
    current = """
[models.chat]
api_url = "https://primary.example/v1"
api_key = "primary-key"
model_name = "primary-model"

[models.chat.request_params]
temperature = 0.2

[models.chat.request_params.metadata]
tier = "gold"

[[models.chat.request_params.tags]]
name = "alpha"

[models.chat.extra]
flag = true
"""
    example = """
[models.chat]
api_url = ""
api_key = ""
model_name = ""

[models.chat.request_params]
"""

    result = sync_config_text(current, example, prune=True)
    parsed = tomllib.loads(result.content)
    request_params = parsed["models"]["chat"]["request_params"]

    assert result.removed_paths == ["models.chat.extra"]
    assert request_params["temperature"] == 0.2
    assert request_params["metadata"]["tier"] == "gold"
    assert request_params["tags"][0]["name"] == "alpha"
    assert "extra" not in parsed["models"]["chat"]
