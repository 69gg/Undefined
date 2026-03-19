from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.services.security import SecurityService


class _FakeRequester:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def request(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "submit_naga_moderation_result",
                                    "arguments": (
                                        '{"decision":"block",'
                                        '"categories":["personal_privacy"],'
                                        '"reason":"contains privacy"}'
                                    ),
                                }
                            }
                        ]
                    }
                }
            ]
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("api_mode", ["chat_completions", "responses"])
async def test_moderate_naga_message_uses_tool_call_for_both_api_modes(
    api_mode: str,
) -> None:
    service = object.__new__(SecurityService)
    requester = _FakeRequester()
    model_config = SimpleNamespace(
        api_mode=api_mode,
        thinking_enabled=False,
        model_name="naga-model",
    )
    service.config = cast(
        Any,
        SimpleNamespace(
            naga_model=model_config,
            security_model=model_config,
        ),
    )
    service._requester = cast(Any, requester)

    result = await service.moderate_naga_message(
        message_format="markdown",
        content="# hello",
    )

    assert result.blocked is True
    assert result.status == "blocked"
    assert result.categories == ["personal_privacy"]
    assert requester.calls
    call = requester.calls[-1]
    assert call["tools"][0]["function"]["name"] == "submit_naga_moderation_result"
    if api_mode == "responses":
        assert call["tool_choice"] == "required"
    else:
        assert call["tool_choice"] == {
            "type": "function",
            "function": {"name": "submit_naga_moderation_result"},
        }


@pytest.mark.asyncio
async def test_moderate_naga_message_returns_error_allowed_when_tool_call_missing() -> (
    None
):
    class _BrokenRequester:
        async def request(self, **kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            return {"choices": [{"message": {"content": "not structured"}}]}

    service = object.__new__(SecurityService)
    model_config = SimpleNamespace(
        api_mode="responses",
        thinking_enabled=False,
        model_name="naga-model",
    )
    service.config = cast(
        Any,
        SimpleNamespace(
            naga_model=model_config,
            security_model=model_config,
        ),
    )
    service._requester = cast(Any, _BrokenRequester())

    result = await service.moderate_naga_message(
        message_format="text",
        content="hello",
    )

    assert result.blocked is False
    assert result.status == "error_allowed"
