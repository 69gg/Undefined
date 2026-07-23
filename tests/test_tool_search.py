"""请求级 Tool Search 内核测试。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from Undefined.ai.tool_search import (
    TOOL_SEARCH_NAME,
    ToolSearchNameCollisionError,
    ToolSearchSession,
)


def _tool(
    name: str,
    description: str = "",
    *,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
            },
        },
    }


def _names(schemas: list[dict[str, Any]]) -> list[str]:
    return [str(schema["function"]["name"]) for schema in schemas]


def test_initial_projection_and_deferred_directory_are_stable() -> None:
    schemas = [_tool("weather.lookup"), _tool("end"), _tool("send_message")]
    session = ToolSearchSession(schemas, ["send_message", "end"], max_results=5)

    assert session.deferred_tool_names == ("weather.lookup",)
    assert _names(session.request_tools()) == ["end", "send_message", TOOL_SEARCH_NAME]
    assert session.exposed_tool_names() == {"send_message", "end", TOOL_SEARCH_NAME}

    schemas[0]["function"]["description"] = "mutated input"
    first_request = session.request_tools()
    first_request[0]["function"]["name"] = "mutated output"
    assert _names(session.request_tools()) == ["end", "send_message", TOOL_SEARCH_NAME]


def test_virtual_schema_uses_configured_result_cap() -> None:
    session = ToolSearchSession([], [], max_results=3)
    function = session.tool_search_schema["function"]

    assert function["name"] == TOOL_SEARCH_NAME
    assert function["parameters"]["properties"]["max_results"]["maximum"] == 3
    assert function["parameters"]["additionalProperties"] is False


def test_name_collision_supports_factory_fallback_and_explicit_exception() -> None:
    schemas = [_tool(TOOL_SEARCH_NAME)]

    assert ToolSearchSession.create(schemas, [], max_results=5) is None
    with pytest.raises(ToolSearchNameCollisionError):
        ToolSearchSession(schemas, [], max_results=5)


def test_hidden_tools_are_absent_from_catalog_directory_and_search() -> None:
    session = ToolSearchSession(
        [_tool("public_tool"), _tool("secret_tool", "private secret capability")],
        [],
        max_results=5,
        hidden_tool_names={"secret_tool"},
    )

    assert session.catalog_tool_names == ("public_tool",)
    assert session.deferred_tool_names == ("public_tool",)
    result = session.search_and_load("select:secret_tool")
    assert result.not_found == ("secret_tool",)
    assert result.loaded == ()


def test_exact_selection_loads_only_for_the_next_request_round() -> None:
    session = ToolSearchSession(
        [_tool("send_message"), _tool("web_agent")],
        ["send_message"],
        max_results=5,
    )
    session.request_tools()

    result = session.search_and_load("select:web_agent")

    assert result.loaded == ("web_agent",)
    assert session.loaded_tool_names == {"send_message", "web_agent"}
    assert session.exposed_tool_names() == {"send_message", TOOL_SEARCH_NAME}
    assert _names(session.request_tools()) == [
        "send_message",
        "web_agent",
        TOOL_SEARCH_NAME,
    ]
    assert session.exposed_tool_names() == {
        "send_message",
        "web_agent",
        TOOL_SEARCH_NAME,
    }


def test_select_is_case_insensitive_deduplicated_partial_and_capped() -> None:
    session = ToolSearchSession(
        [_tool("alpha"), _tool("beta"), _tool("gamma")],
        [],
        max_results=2,
    )

    result = session.search_and_load(
        "select:ALPHA,missing,alpha,beta,gamma", max_results=99
    )

    assert result.loaded == ("alpha", "beta")
    assert result.not_found == ("missing",)
    assert result.truncated is True
    assert result.total_deferred_tools == 3


def test_bare_full_name_reports_already_loaded() -> None:
    session = ToolSearchSession([_tool("send_message")], ["send_message"], 5)

    result = session.search_and_load("SEND_MESSAGE")

    assert result.loaded == ()
    assert result.already_loaded == ("send_message",)


def test_exact_catalog_case_variant_takes_priority_over_virtual_name() -> None:
    session = ToolSearchSession([_tool("Tool_Search")], [], max_results=5)

    real_result = session.search_and_load("select:Tool_Search")
    virtual_result = session.search_and_load("select:tool_search")

    assert real_result.loaded == ("Tool_Search",)
    assert real_result.already_loaded == ()
    assert virtual_result.loaded == ()
    assert virtual_result.already_loaded == (TOOL_SEARCH_NAME,)


def test_keyword_scoring_uses_name_parameter_and_descriptions() -> None:
    session = ToolSearchSession(
        [
            _tool("weather_current", "unrelated"),
            _tool("weather_forecast", "unrelated"),
            _tool(
                "lookup",
                "unrelated",
                properties={"weather_city": {"type": "string"}},
            ),
            _tool("generic", "weather observations"),
        ],
        [],
        max_results=4,
    )

    result = session.search_and_load("weather")

    assert result.loaded == (
        "weather_current",
        "weather_forecast",
        "lookup",
        "generic",
    )


@pytest.mark.parametrize("query", ["search_songs", "load music.search_songs"])
def test_keyword_query_normalizes_tool_name_separators(query: str) -> None:
    session = ToolSearchSession(
        [
            _tool("music.search_songs", "Search songs across music platforms"),
            _tool("music.get_hot_search", "Next call music.search_songs"),
            _tool("music.get_lyrics", "Track from music.search_songs"),
        ],
        [],
        max_results=1,
    )

    result = session.search_and_load(query)

    assert result.loaded == ("music.search_songs",)
    assert result.truncated is True


def test_nested_parameter_descriptions_are_searchable() -> None:
    nested_properties = {
        "filters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "Meteorological station name",
                }
            },
        }
    }
    session = ToolSearchSession(
        [_tool("lookup", properties=nested_properties)], [], max_results=5
    )

    result = session.search_and_load("meteorological")

    assert result.loaded == ("lookup",)


def test_required_terms_filter_candidates_before_optional_ranking() -> None:
    session = ToolSearchSession(
        [
            _tool("slack_send", "send a channel message"),
            _tool("email_send", "send a message"),
            _tool("slack_read", "read a channel message"),
        ],
        [],
        max_results=5,
    )

    result = session.search_and_load("+slack send")

    assert result.loaded == ("slack_send", "slack_read")


def test_keyword_ties_are_sorted_by_canonical_name() -> None:
    session = ToolSearchSession(
        [_tool("zeta", "shared capability"), _tool("Alpha", "shared capability")],
        [],
        max_results=5,
    )

    assert session.search_and_load("shared").loaded == ("Alpha", "zeta")


def test_requested_max_results_can_only_shrink_configured_limit() -> None:
    schemas = [_tool(f"search_{index}", "common") for index in range(4)]
    small = ToolSearchSession(schemas, [], max_results=3)
    large = ToolSearchSession(schemas, [], max_results=3)

    small_result = small.search_and_load("common", max_results=1)
    large_result = large.search_and_load("common", max_results=100)

    assert len(small_result.loaded) == 1
    assert small_result.truncated is True
    assert len(large_result.loaded) == 3
    assert large_result.truncated is True


def test_repeated_keyword_search_reports_existing_matches_without_reordering() -> None:
    session = ToolSearchSession(
        [_tool("alpha_find", "lookup"), _tool("beta_find", "lookup")],
        [],
        max_results=2,
    )

    first = session.search_and_load("lookup")
    second = session.search_and_load("lookup")

    assert first.loaded == ("alpha_find", "beta_find")
    assert second.loaded == ()
    assert second.already_loaded == ("alpha_find", "beta_find")


def test_no_keyword_match_returns_query_as_not_found() -> None:
    session = ToolSearchSession([_tool("calculator")], [], max_results=5)

    result = session.search_and_load("calendar")

    assert result.loaded == ()
    assert result.not_found == ("calendar",)
    assert result.truncated is False


def test_execute_returns_required_json_shape_and_ignores_external_schema() -> None:
    session = ToolSearchSession([_tool("known_tool")], [], max_results=5)

    payload = json.loads(
        session.execute(
            {
                "query": "select:injected_tool",
                "schema": _tool("injected_tool"),
                "max_results": 500,
            }
        )
    )

    assert payload == {
        "loaded": [],
        "already_loaded": [],
        "not_found": ["injected_tool"],
        "truncated": False,
        "total_deferred_tools": 1,
    }
    assert "injected_tool" not in session.loaded_tool_names


def test_malformed_and_duplicate_schemas_do_not_destabilize_catalog() -> None:
    schemas: list[dict[str, Any]] = [
        {},
        {"type": "function", "function": {"name": ""}},
        _tool("valid", "first"),
        _tool("valid", "second"),
    ]

    session = ToolSearchSession(schemas, [], max_results=5)

    assert session.catalog_tool_names == ("valid",)
    assert session.search_and_load("first").loaded == ("valid",)


def test_invalid_configured_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        ToolSearchSession([], [], max_results=0)
