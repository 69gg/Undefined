"""render_toml array-of-tables 单元测试"""

import tomllib

from Undefined.webui.utils import render_toml


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
