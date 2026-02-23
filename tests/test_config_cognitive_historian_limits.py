from __future__ import annotations

from Undefined.config.loader import Config


def test_parse_cognitive_historian_reference_limits() -> None:
    cfg = Config._parse_cognitive_config(
        {
            "cognitive": {
                "query": {"enable_rerank": False},
                "historian": {
                    "recent_messages_inject_k": 21,
                    "recent_message_line_max_len": 333,
                    "source_message_max_len": 1200,
                },
            }
        }
    )

    assert cfg.historian_recent_messages_inject_k == 21
    assert cfg.historian_recent_message_line_max_len == 333
    assert cfg.historian_source_message_max_len == 1200
    assert cfg.enable_rerank is False


def test_parse_cognitive_historian_reference_limits_defaults() -> None:
    cfg = Config._parse_cognitive_config({"cognitive": {}})

    assert cfg.historian_recent_messages_inject_k == 12
    assert cfg.historian_recent_message_line_max_len == 240
    assert cfg.historian_source_message_max_len == 800
    assert cfg.enable_rerank is True
