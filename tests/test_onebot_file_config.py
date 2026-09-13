from pathlib import Path
import pytest

from Undefined.config.loader import Config
from Undefined.config.onebot import parse_file_send_host, parse_file_send_mode
from Undefined.config.load_sections.core import load_core
from Undefined.config.env_registry import ENV_REGISTRY


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "stream"),
        ("", "stream"),
        ("   ", "stream"),
        (" Stream ", "stream"),
        ("url", "url"),
        ("LOCAL", "local"),
    ],
)
def test_mode_normalization(raw: str | None, expected: str) -> None:
    assert parse_file_send_mode(raw) == expected


@pytest.mark.parametrize("raw", ["auto", "base64", "stream api"])
def test_invalid_mode_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match="onebot.file_send_mode"):
        load_core({"onebot": {"file_send_mode": raw}})


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "127.0.0.1"),
        ("", "127.0.0.1"),
        ("example.com", "example.com"),
        ("::1", "::1"),
        ("[::1]", "::1"),
        ("192.168.1.2", "192.168.1.2"),
    ],
)
def test_host_normalization(raw: str | None, expected: str) -> None:
    assert parse_file_send_host(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "http://localhost",
        "localhost:8788",
        "localhost/path",
        "user@host",
        "[localhost]",
        "bad host",
        "127.0.0.1?x=1",
        "::1%/path",
    ],
)
def test_host_rejects_non_host(raw: str) -> None:
    with pytest.raises(ValueError, match="onebot.file_send_host"):
        parse_file_send_host(raw)


def test_env_precedence_and_loaded_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEBOT_FILE_SEND_MODE", " URL ")
    monkeypatch.setenv("ONEBOT_FILE_SEND_HOST", "::1")
    values = load_core({})
    assert values["onebot_file_send_mode"] == "url"
    assert values["onebot_file_send_host"] == "::1"
    assert (
        load_core({"onebot": {"file_send_mode": "local"}})["onebot_file_send_mode"]
        == "local"
    )
    # TOML 空值也遵循 TOML 优先，使用默认值而非环境变量。
    assert (
        load_core({"onebot": {"file_send_mode": ""}})["onebot_file_send_mode"]
        == "stream"
    )
    path = tmp_path / "config.toml"
    path.write_text(
        '[onebot]\nfile_send_mode = "stream"\nfile_send_host = "127.0.0.1"\n'
    )
    cfg = Config.load(path, strict=False)
    assert cfg.onebot_file_send_mode == "stream"
    assert cfg.onebot_file_send_host == "127.0.0.1"
    assert ENV_REGISTRY[("onebot", "file_send_mode")] == "ONEBOT_FILE_SEND_MODE"
    assert ENV_REGISTRY[("onebot", "file_send_host")] == "ONEBOT_FILE_SEND_HOST"
