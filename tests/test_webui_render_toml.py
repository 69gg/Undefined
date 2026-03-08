"""render_toml array-of-tables 单元测试"""

import tomllib

from Undefined.webui.utils import parse_comment_map_text, render_toml


def _roundtrip(toml_str: str) -> dict:  # type: ignore[type-arg]
    data = tomllib.loads(toml_str)
    rendered = render_toml(data)
    return tomllib.loads(rendered)


class TestRenderTomlArrayOfTables:
    def test_pool_models_roundtrip(self) -> None:
        """[[models.chat.pool.models]] 经过 render_toml 后结构不变"""
        src = """
[models.chat.pool]
enabled = true
strategy = "round_robin"

[[models.chat.pool.models]]
model_name = "gpt-4o"
api_url = "https://api.openai.com/v1"
api_key = "sk-a"

[[models.chat.pool.models]]
model_name = "deepseek-chat"
api_url = "https://api.deepseek.com/v1"
api_key = "sk-b"
"""
        data = _roundtrip(src)
        pool = data["models"]["chat"]["pool"]
        assert pool["enabled"] is True
        assert pool["strategy"] == "round_robin"
        assert len(pool["models"]) == 2
        assert pool["models"][0]["model_name"] == "gpt-4o"
        assert pool["models"][1]["api_key"] == "sk-b"

    def test_empty_list_stays_inline(self) -> None:
        """空列表仍渲染为内联数组"""
        rendered = render_toml({"allowed": []})
        assert "allowed = []" in rendered

    def test_scalar_list_stays_inline(self) -> None:
        """标量列表仍渲染为内联数组"""
        data = _roundtrip("ids = [1, 2, 3]")
        assert data["ids"] == [1, 2, 3]

    def test_aot_not_rendered_as_string(self) -> None:
        """list[dict] 不能被渲染成字符串形式"""
        src = """
[[items]]
name = "a"
[[items]]
name = "b"
"""
        rendered = render_toml(tomllib.loads(src))
        assert '"{' not in rendered
        assert "[[items]]" in rendered

    def test_pool_model_request_params_roundtrip(self) -> None:
        """模型池条目下的 request_params 嵌套结构应完整往返"""
        src = """
[models.chat.pool]
enabled = true

[[models.chat.pool.models]]
model_name = "gpt-5"
api_url = "https://api.openai.com/v1"
api_key = "sk-a"
api_mode = "responses"
thinking_tool_call_compat = true
responses_tool_choice_compat = true
responses_force_stateless_replay = true
reasoning_enabled = true
reasoning_effort = "high"

[models.chat.pool.models.request_params]
temperature = 0.7

[models.chat.pool.models.request_params.metadata]
source = "webui"

[[models.chat.pool.models.request_params.tags]]
name = "alpha"

[[models.chat.pool.models.request_params.tags]]
name = "beta"
"""
        data = _roundtrip(src)
        model = data["models"]["chat"]["pool"]["models"][0]
        assert model["api_mode"] == "responses"
        assert model["thinking_tool_call_compat"] is True
        assert model["responses_tool_choice_compat"] is True
        assert model["responses_force_stateless_replay"] is True
        assert model["reasoning_enabled"] is True
        assert model["reasoning_effort"] == "high"
        params = model["request_params"]
        assert params["temperature"] == 0.7
        assert params["metadata"]["source"] == "webui"
        assert [item["name"] for item in params["tags"]] == ["alpha", "beta"]

    def test_nested_aot_child_tables_roundtrip(self) -> None:
        """数组表项下的嵌套表与子数组表不能在渲染时丢失"""
        src = """
[[items]]
name = "root"

[items.meta]
enabled = true

[[items.meta.children]]
name = "child-a"

[[items.meta.children]]
name = "child-b"
"""
        data = _roundtrip(src)
        item = data["items"][0]
        assert item["meta"]["enabled"] is True
        assert [child["name"] for child in item["meta"]["children"]] == [
            "child-a",
            "child-b",
        ]

    def test_render_comments_and_empty_table(self) -> None:
        """带注释的空表应被完整渲染出来"""
        src = """
# zh: 主配置
# en: Main section
[models.chat.request_params]
"""
        comments = parse_comment_map_text(src)
        rendered = render_toml(
            {"models": {"chat": {"request_params": {}}}}, comments=comments
        )
        assert "# zh: 主配置" in rendered
        assert "[models.chat.request_params]" in rendered

    def test_render_comments_before_scalar_keys(self) -> None:
        """标量字段前应写出示例注释"""
        comments = {
            "core.bot_qq": {
                "zh": "机器人QQ号。",
                "en": "Bot QQ number.",
            }
        }
        rendered = render_toml({"core": {"bot_qq": 1}}, comments=comments)
        assert "# zh: 机器人QQ号。" in rendered
        assert "# en: Bot QQ number." in rendered
        assert "bot_qq = 1" in rendered

    def test_multiline_string_roundtrip(self) -> None:
        """多行字符串应被渲染成合法 TOML，并可完整往返"""
        original = "第一行\n第二行\n第三行"
        rendered = render_toml(
            {"models": {"embedding": {"query_instruction": original}}}
        )
        parsed = tomllib.loads(rendered)
        assert parsed["models"]["embedding"]["query_instruction"] == original
        assert "\n" in rendered

    def test_multiline_string_with_quotes_and_backslashes_roundtrip(self) -> None:
        """带引号与反斜杠的多行字符串也必须是合法 TOML"""
        original = 'prefix "quoted"\npath\\to\\file\nline3'
        rendered = render_toml(
            {"models": {"embedding": {"document_instruction": original}}}
        )
        parsed = tomllib.loads(rendered)
        assert parsed["models"]["embedding"]["document_instruction"] == original
