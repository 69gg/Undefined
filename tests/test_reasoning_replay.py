from __future__ import annotations

from copy import deepcopy
from typing import Any

from Undefined.ai.llm.requester import build_request_body
from Undefined.ai.llm.streaming import (
    aggregate_chat_completions_stream,
    aggregate_responses_stream,
)
from Undefined.ai.transports import (
    CHAT_REASONING_REPLAY_KEY,
    RESPONSES_OUTPUT_ITEMS_KEY,
    RESPONSES_REASONING_REPLAY_KEY,
    normalize_chat_completions_result,
    normalize_responses_result,
)
from Undefined.config.models import ChatModelConfig


def _chat_config(**overrides: Any) -> ChatModelConfig:
    values: dict[str, Any] = {
        "api_url": "https://api.example.com/v1",
        "api_key": "sk-test",
        "model_name": "reasoning-model",
        "max_tokens": 4096,
    }
    values.update(overrides)
    return ChatModelConfig(**values)


def test_chat_replay_prefers_original_reasoning_fields() -> None:
    reasoning_details = [
        {
            "type": "reasoning.summary",
            "summary": "plan first",
            "id": "summary-1",
            "format": "anthropic-claude-v1",
            "index": 0,
        },
        {
            "type": "reasoning.text",
            "text": "private analysis",
            "signature": "sig-1",
            "id": "text-1",
            "format": "anthropic-claude-v1",
            "index": 1,
        },
        {
            "type": "reasoning.encrypted",
            "data": "ciphertext",
            "id": "encrypted-1",
            "format": "anthropic-claude-v1",
            "index": 2,
        },
    ]
    result = normalize_chat_completions_result(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "answer",
                        "reasoning_details": reasoning_details,
                        "encrypted_content": "opaque-cot",
                        "thinking": {"text": "native thinking", "signature": "sig-2"},
                    }
                }
            ]
        }
    )
    message = result["choices"][0]["message"]
    assert message["reasoning_content"] == "plan first\nprivate analysis"
    original_wire = deepcopy(message[CHAT_REASONING_REPLAY_KEY])

    body = build_request_body(
        model_config=_chat_config(),
        messages=[message],
        max_tokens=512,
    )

    outbound = body["messages"][0]
    assert outbound["reasoning_details"] == reasoning_details
    assert outbound["encrypted_content"] == "opaque-cot"
    assert outbound["thinking"] == {
        "text": "native thinking",
        "signature": "sig-2",
    }
    assert "reasoning_content" not in outbound
    assert message[CHAT_REASONING_REPLAY_KEY] == original_wire


def test_chat_replay_switch_strips_every_reasoning_wire_field() -> None:
    message = {
        "role": "assistant",
        "content": "answer",
        "reasoning_content": "readable",
        "reasoning_details": [{"type": "reasoning.encrypted", "data": "cipher"}],
        "reasoning": {"text": "structured"},
        "encrypted_content": "opaque",
        "thinking": {"text": "thinking", "signature": "sig"},
        CHAT_REASONING_REPLAY_KEY: {
            "reasoning_details": [{"type": "reasoning.encrypted", "data": "cipher"}],
            "encrypted_content": "opaque",
        },
    }
    body = build_request_body(
        model_config=_chat_config(reasoning_content_replay=False),
        messages=[message],
        max_tokens=512,
    )

    assert body["messages"] == [{"role": "assistant", "content": "answer"}]


def test_chat_stream_preserves_reasoning_detail_order_and_encrypted_chunks() -> None:
    chunks: list[dict[str, Any]] = [
        {
            "choices": [
                {
                    "delta": {
                        "reasoning_details": [
                            {
                                "type": "reasoning.summary",
                                "summary": "summary",
                                "index": 0,
                            }
                        ],
                        "encrypted_content": "cipher-",
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "reasoning_details": [
                            {
                                "type": "reasoning.encrypted",
                                "data": "payload",
                                "signature": "sig",
                                "index": 1,
                            }
                        ],
                        "encrypted_content": "tail",
                    },
                    "finish_reason": "stop",
                }
            ]
        },
    ]

    message = aggregate_chat_completions_stream(chunks)["choices"][0]["message"]

    assert [item["index"] for item in message["reasoning_details"]] == [0, 1]
    assert message["encrypted_content"] == "cipher-tail"
    assert (
        message[CHAT_REASONING_REPLAY_KEY]["reasoning_details"]
        == message["reasoning_details"]
    )


def test_responses_replays_native_reasoning_item_before_readable_fallback() -> None:
    native_reasoning = {
        "type": "reasoning",
        "id": "rs_1",
        "summary": [{"type": "summary_text", "text": "summary"}],
        "content": [{"type": "reasoning_text", "text": "analysis"}],
        "encrypted_content": "cipher",
        "status": "completed",
    }
    message = {
        "role": "assistant",
        "content": "",
        "reasoning_content": "legacy fallback must not be added",
        RESPONSES_OUTPUT_ITEMS_KEY: [native_reasoning],
    }
    body = build_request_body(
        model_config=_chat_config(api_mode="openai.responses"),
        messages=[message],
        max_tokens=512,
        transport_state={"stateless_replay": True},
    )

    expected_reasoning = dict(native_reasoning)
    expected_reasoning.pop("status")
    assert body["input"] == [expected_reasoning]


def test_responses_old_readable_reasoning_fallback_without_raw_metadata() -> None:
    body = build_request_body(
        model_config=_chat_config(api_mode="openai.responses"),
        messages=[
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "legacy readable reasoning",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": "{}"},
                    }
                ],
            }
        ],
        max_tokens=512,
        transport_state={"stateless_replay": True},
    )

    assert body["input"] == [
        {
            "type": "message",
            "role": "assistant",
            "content": [],
            "reasoning_content": "legacy readable reasoning",
        },
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": "{}",
        },
    ]

    disabled_body = build_request_body(
        model_config=_chat_config(
            api_mode="openai.responses",
            reasoning_content_replay=False,
        ),
        messages=[
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "legacy readable reasoning",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": "{}"},
                    }
                ],
            }
        ],
        max_tokens=512,
        transport_state={"stateless_replay": True},
    )
    assert disabled_body["input"] == [
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": "{}",
        }
    ]


def test_responses_compatible_root_reasoning_fields_are_replayed_losslessly() -> None:
    reasoning_details = [
        {"type": "reasoning.encrypted", "data": "cipher", "signature": "sig"}
    ]
    normalized = normalize_responses_result(
        {
            "id": "resp_1",
            "output": [
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "lookup",
                    "arguments": "{}",
                }
            ],
            "reasoning_content": "gateway-readable-reasoning",
            "reasoning_details": reasoning_details,
            "encrypted_content": "gateway-ciphertext",
        }
    )
    message = normalized["choices"][0]["message"]

    body = build_request_body(
        model_config=_chat_config(api_mode="openai.responses"),
        messages=[message],
        max_tokens=512,
        transport_state={"stateless_replay": True},
    )

    compat_message, function_call = body["input"]
    assert compat_message["role"] == "assistant"
    assert compat_message["reasoning_content"] == "gateway-readable-reasoning"
    assert compat_message["reasoning_details"] == reasoning_details
    assert compat_message["encrypted_content"] == "gateway-ciphertext"
    assert function_call["id"] == "fc_1"


def test_responses_root_reasoning_config_is_not_treated_as_output_cot() -> None:
    normalized = normalize_responses_result(
        {
            "id": "resp_1",
            "reasoning": {"effort": "high", "summary": "auto"},
            "output": [
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "lookup",
                    "arguments": "{}",
                }
            ],
        }
    )
    message = normalized["choices"][0]["message"]

    assert "reasoning_content" not in message
    assert RESPONSES_REASONING_REPLAY_KEY not in message

    body = build_request_body(
        model_config=_chat_config(api_mode="openai.responses"),
        messages=[message],
        max_tokens=512,
        transport_state={"stateless_replay": True},
    )
    assert body["input"] == [
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": "{}",
        }
    ]


def test_responses_replay_switch_filters_native_and_embedded_reasoning() -> None:
    normalized = normalize_responses_result(
        {
            "output": [
                {
                    "type": "reasoning",
                    "id": "rs_1",
                    "summary": [{"type": "summary_text", "text": "summary"}],
                    "encrypted_content": "cipher",
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "reasoning_content": "compat reasoning",
                    "reasoning_details": [
                        {"type": "reasoning.encrypted", "data": "cipher"}
                    ],
                    "content": [
                        {"type": "reasoning_text", "text": "analysis"},
                        {"type": "output_text", "text": "answer"},
                    ],
                },
            ]
        }
    )
    message = normalized["choices"][0]["message"]
    body = build_request_body(
        model_config=_chat_config(
            api_mode="openai.responses", reasoning_content_replay=False
        ),
        messages=[message],
        max_tokens=512,
        transport_state={"stateless_replay": True},
    )

    assert body["input"] == [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "answer"}],
        }
    ]


def test_responses_replay_is_enabled_by_default_and_can_be_disabled() -> None:
    default_body = build_request_body(
        model_config=_chat_config(api_mode="openai.responses"),
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=512,
    )
    disabled_body = build_request_body(
        model_config=_chat_config(
            api_mode="openai.responses", reasoning_content_replay=False
        ),
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=512,
    )

    assert default_body["include"] == ["reasoning.encrypted_content"]
    assert "include" not in disabled_body

    explicitly_disabled_body = build_request_body(
        model_config=_chat_config(
            api_mode="openai.responses", reasoning_content_replay=False
        ),
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=512,
        include=["reasoning.encrypted_content", "file_search_call.results"],
    )
    assert explicitly_disabled_body["include"] == ["file_search_call.results"]


def test_responses_stateful_followup_resends_current_instructions() -> None:
    body = build_request_body(
        model_config=_chat_config(api_mode="openai.responses"),
        messages=[
            {"role": "system", "content": "system instruction"},
            {"role": "user", "content": "question"},
            {"role": "tool", "tool_call_id": "call_1", "content": "result"},
        ],
        max_tokens=512,
        transport_state={
            "previous_response_id": "resp_1",
            "tool_result_start_index": 2,
        },
    )

    assert body["instructions"] == "system instruction"
    assert body["previous_response_id"] == "resp_1"
    assert body["input"] == [
        {"type": "function_call_output", "call_id": "call_1", "output": "result"}
    ]


def test_responses_stream_reconstructs_reasoning_and_function_arguments() -> None:
    events: list[dict[str, Any]] = [
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {"type": "reasoning", "id": "rs_1", "summary": []},
        },
        {
            "type": "response.reasoning_summary_part.added",
            "output_index": 0,
            "summary_index": 0,
            "item_id": "rs_1",
            "part": {"type": "summary_text", "text": ""},
        },
        {
            "type": "response.reasoning_summary_text.delta",
            "output_index": 0,
            "summary_index": 0,
            "item_id": "rs_1",
            "delta": "summary",
        },
        {
            "type": "response.reasoning_text.delta",
            "output_index": 0,
            "content_index": 0,
            "item_id": "rs_1",
            "delta": "analysis",
        },
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "lookup",
                "arguments": "",
            },
        },
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 1,
            "item_id": "fc_1",
            "delta": '{"query":"weather"}',
        },
    ]

    result = aggregate_responses_stream(events)

    assert result["output"] == [
        {
            "type": "reasoning",
            "id": "rs_1",
            "summary": [{"type": "summary_text", "text": "summary"}],
            "content": [{"type": "reasoning_text", "text": "analysis"}],
        },
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": '{"query":"weather"}',
        },
    ]
