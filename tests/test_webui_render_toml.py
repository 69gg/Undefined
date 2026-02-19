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
