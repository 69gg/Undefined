from __future__ import annotations

from Undefined.config import Config


def test_weixin_config_defaults_disabled() -> None:
    config = Config.from_mapping({}, strict=False)

    assert config.weixin.enabled is False
    assert config.weixin.state_dir == "data/weixin"
    assert config.weixin.media_max_size_mb == 100


def test_weixin_config_coerces_bounds() -> None:
    config = Config.from_mapping(
        {
            "weixin": {
                "enabled": True,
                "state_dir": "runtime/weixin",
                "long_poll_timeout_seconds": 0,
                "failures_before_backoff": 0,
                "media_max_size_mb": -1,
                "login_session_ttl_seconds": 1,
            }
        },
        strict=False,
    )

    assert config.weixin.enabled is True
    assert config.weixin.state_dir == "runtime/weixin"
    assert config.weixin.long_poll_timeout_seconds == 1.0
    assert config.weixin.failures_before_backoff == 1
    assert config.weixin.media_max_size_mb == 1
    assert config.weixin.login_session_ttl_seconds == 30.0
