"""Additional tests for Undefined root package lazy re-export mechanism.

Covers behaviors not already tested in test_public_api_imports.py:
- __getattr__ raises AttributeError for unknown names
- __getattr__ caches loaded symbol in globals()
- _LAZY_IMPORTS structure consistency with __all__
- Module-level version string
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# __version__
# ---------------------------------------------------------------------------


def test_version_is_string() -> None:
    import Undefined
    assert isinstance(Undefined.__version__, str)
    assert len(Undefined.__version__) > 0


def test_version_format_is_semver_like() -> None:
    import Undefined
    parts = Undefined.__version__.split(".")
    assert len(parts) == 3
    for part in parts:
        assert part.isdigit(), f"Non-numeric version part: {part!r}"


# ---------------------------------------------------------------------------
# __all__ structure
# ---------------------------------------------------------------------------


def test_all_contains_version_string() -> None:
    import Undefined
    assert "__version__" in Undefined.__all__


def test_all_is_list_of_strings() -> None:
    import Undefined
    assert isinstance(Undefined.__all__, list)
    for item in Undefined.__all__:
        assert isinstance(item, str), f"Non-string in __all__: {item!r}"


def test_lazy_imports_keys_match_all_except_version() -> None:
    """Every symbol in __all__ (except __version__) must have a lazy import entry."""
    import Undefined
    from Undefined import _LAZY_IMPORTS

    all_symbols = set(Undefined.__all__)
    all_symbols.discard("__version__")
    assert all_symbols == set(_LAZY_IMPORTS.keys())


# ---------------------------------------------------------------------------
# __getattr__ — unknown attribute raises AttributeError
# ---------------------------------------------------------------------------


def test_getattr_unknown_attribute_raises() -> None:
    import Undefined
    with pytest.raises(AttributeError, match="no attribute"):
        _ = Undefined.NonExistentSymbol  # type: ignore[attr-defined]


def test_getattr_dunder_attribute_raises() -> None:
    import Undefined
    with pytest.raises(AttributeError):
        _ = Undefined.__nonexistent__  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# __getattr__ — caching behavior
# ---------------------------------------------------------------------------


def test_getattr_caches_symbol_in_globals() -> None:
    """After first access, the symbol should be cached so __getattr__ isn't called again."""
    import Undefined

    # Access once to trigger lazy loading
    cfg_class = Undefined.Config  # noqa: F841

    # The symbol should now be in the module's __dict__ / globals
    assert "Config" in vars(Undefined)


def test_cached_symbol_is_same_object_on_repeated_access() -> None:
    import Undefined

    first = Undefined.Config
    second = Undefined.Config
    assert first is second


# ---------------------------------------------------------------------------
# _LAZY_IMPORTS — module paths and attribute names
# ---------------------------------------------------------------------------


def test_lazy_imports_values_are_tuples_of_two_strings() -> None:
    from Undefined import _LAZY_IMPORTS

    for symbol, entry in _LAZY_IMPORTS.items():
        assert isinstance(entry, tuple), f"Entry for {symbol!r} is not a tuple"
        assert len(entry) == 2, f"Entry for {symbol!r} does not have 2 elements"
        module_path, attr = entry
        assert isinstance(module_path, str), f"Module path for {symbol!r} is not a string"
        assert isinstance(attr, str), f"Attribute for {symbol!r} is not a string"
        assert module_path.startswith("Undefined."), (
            f"Module path for {symbol!r} doesn't start with 'Undefined.': {module_path!r}"
        )


def test_lazy_imports_config_points_to_correct_module() -> None:
    from Undefined import _LAZY_IMPORTS

    module_path, attr = _LAZY_IMPORTS["Config"]
    assert module_path == "Undefined.config"
    assert attr == "Config"


def test_lazy_imports_ai_client_points_to_correct_module() -> None:
    from Undefined import _LAZY_IMPORTS

    module_path, attr = _LAZY_IMPORTS["AIClient"]
    assert module_path == "Undefined.ai"
    assert attr == "AIClient"


# ---------------------------------------------------------------------------
# ai/client/__init__.py module-level symbols
# ---------------------------------------------------------------------------


def test_ai_client_module_exports_missing_tool_call_hint() -> None:
    from Undefined.ai.client import MISSING_TOOL_CALL_RETRY_HINT

    assert isinstance(MISSING_TOOL_CALL_RETRY_HINT, str)
    assert len(MISSING_TOOL_CALL_RETRY_HINT) > 0


def test_ai_client_module_exports_invalid_tool_call_content() -> None:
    from Undefined.ai.client import _INVALID_TOOL_CALL_CONTENT

    assert isinstance(_INVALID_TOOL_CALL_CONTENT, str)
    assert "工具名称为空" in _INVALID_TOOL_CALL_CONTENT


def test_ai_client_module_all_contains_expected_symbols() -> None:
    import Undefined.ai.client as client_mod

    expected_symbols = {
        "AIClient",
        "MISSING_TOOL_CALL_RETRY_HINT",
        "SendMessageCallback",
        "SendPrivateMessageCallback",
        "_INVALID_TOOL_CALL_CONTENT",
        "_build_invalid_tool_call_response",
        "_resolve_summary_model_config",
        "fetch_session_messages",
    }
    assert set(client_mod.__all__) == expected_symbols


# ---------------------------------------------------------------------------
# ai/llm/__init__.py module-level symbols
# ---------------------------------------------------------------------------


def test_llm_module_exports_model_requester() -> None:
    from Undefined.ai.llm import ModelRequester
    assert ModelRequester is not None


def test_llm_module_exports_model_config_type() -> None:
    from Undefined.ai.llm import ModelConfig
    # Should be a union type alias, not None
    assert ModelConfig is not None


def test_llm_module_exports_encode_tool_name() -> None:
    from Undefined.ai.llm import _encode_tool_name_for_api
    assert callable(_encode_tool_name_for_api)


def test_llm_module_exports_should_fallback_alias() -> None:
    from Undefined.ai.llm import _should_fallback_from_stream, should_fallback_from_stream
    # The private alias should point to the same function
    assert _should_fallback_from_stream is should_fallback_from_stream


def test_llm_module_all_contains_expected_symbols() -> None:
    import Undefined.ai.llm as llm_mod

    for symbol in ("ModelRequester", "build_request_body", "ModelConfig",
                   "_encode_tool_name_for_api", "_should_fallback_from_stream"):
        assert symbol in llm_mod.__all__, f"{symbol!r} missing from llm __all__"
