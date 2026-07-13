from __future__ import annotations

from pathlib import Path

from Undefined.config.loader import Config


def _load_config(path: Path, text: str) -> Config:
    path.write_text(text, "utf-8")
    return Config.load(path, strict=False)


def test_api_config_defaults_when_missing(tmp_path: Path) -> None:
    cfg = _load_config(tmp_path / "config.toml", "")
    assert cfg.api.enabled is True
    assert cfg.api.host == "127.0.0.1"
    assert cfg.api.port == 8788
    assert cfg.api.auth_key == "changeme"
    assert cfg.api.openapi_enabled is True
    assert cfg.api.tool_invoke_enabled is False
    assert cfg.api.tool_invoke_expose == "tools+toolsets"
    assert cfg.api.tool_invoke_allowlist == []
    assert cfg.api.tool_invoke_denylist == []
    assert cfg.api.tool_invoke_timeout == 120
    assert cfg.api.tool_invoke_callback_timeout == 10
    assert cfg.attachment_remote_download_max_size_mb == 25
    assert cfg.attachment_cache_max_total_size_mb == 0
    assert cfg.attachment_cache_max_records == 2000
    assert cfg.attachment_cache_max_age_days == 7
    assert cfg.attachment_url_reference_max_records == 2000
    assert cfg.attachment_url_max_length == 8192


def test_attachment_limits_config(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[attachments]
remote_download_max_size_mb = 8
cache_max_total_size_mb = 512
cache_max_records = 300
cache_max_age_days = 14
url_reference_max_records = 150
url_max_length = 4096
""",
    )

    assert cfg.attachment_remote_download_max_size_mb == 8
    assert cfg.attachment_cache_max_total_size_mb == 512
    assert cfg.attachment_cache_max_records == 300
    assert cfg.attachment_cache_max_age_days == 14
    assert cfg.attachment_url_reference_max_records == 150
    assert cfg.attachment_url_max_length == 4096


def test_attachment_limits_invalid_values_fallback(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[attachments]
remote_download_max_size_mb = -1
cache_max_total_size_mb = -512
cache_max_records = -300
cache_max_age_days = -14
url_reference_max_records = -150
url_max_length = -4096
""",
    )

    assert cfg.attachment_remote_download_max_size_mb == 0
    assert cfg.attachment_cache_max_total_size_mb == 0
    assert cfg.attachment_cache_max_records == 0
    assert cfg.attachment_cache_max_age_days == 0
    assert cfg.attachment_url_reference_max_records == 0
    assert cfg.attachment_url_max_length == 0


def test_bilibili_danmaku_config_defaults_and_fallback(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[bilibili]
danmaku_enabled = true
danmaku_batch_size = -1
danmaku_max_count = -99
""",
    )

    assert cfg.bilibili_danmaku_enabled is True
    assert cfg.bilibili_danmaku_batch_size == 100
    assert cfg.bilibili_danmaku_max_count == 0


def test_bilibili_danmaku_config_custom(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[bilibili]
danmaku_enabled = false
danmaku_batch_size = 50
danmaku_max_count = 500
""",
    )

    assert cfg.bilibili_danmaku_enabled is False
    assert cfg.bilibili_danmaku_batch_size == 50
    assert cfg.bilibili_danmaku_max_count == 500


def test_api_config_custom_values(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[api]
enabled = false
host = "0.0.0.0"
port = 9010
auth_key = "secret-key"
openapi_enabled = false
""",
    )
    assert cfg.api.enabled is False
    assert cfg.api.host == "0.0.0.0"
    assert cfg.api.port == 9010
    assert cfg.api.auth_key == "secret-key"
    assert cfg.api.openapi_enabled is False


def test_api_config_invalid_values_fallback(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[api]
port = 99999
auth_key = ""
""",
    )
    assert cfg.api.port == 8788
    assert cfg.api.auth_key == "changeme"


def test_api_tool_invoke_config_custom(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[api]
tool_invoke_enabled = true
tool_invoke_expose = "all"
tool_invoke_allowlist = ["get_current_time", "end"]
tool_invoke_denylist = ["python_interpreter"]
tool_invoke_timeout = 60
tool_invoke_callback_timeout = 5
""",
    )
    assert cfg.api.tool_invoke_enabled is True
    assert cfg.api.tool_invoke_expose == "all"
    assert cfg.api.tool_invoke_allowlist == ["get_current_time", "end"]
    assert cfg.api.tool_invoke_denylist == ["python_interpreter"]
    assert cfg.api.tool_invoke_timeout == 60
    assert cfg.api.tool_invoke_callback_timeout == 5


def test_api_tool_invoke_invalid_expose_fallback(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[api]
tool_invoke_expose = "invalid_value"
""",
    )
    assert cfg.api.tool_invoke_expose == "tools+toolsets"


def test_api_tool_invoke_invalid_timeout_fallback(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[api]
tool_invoke_timeout = -1
tool_invoke_callback_timeout = 0
""",
    )
    assert cfg.api.tool_invoke_timeout == 120
    assert cfg.api.tool_invoke_callback_timeout == 10


def test_render_config_defaults_to_auto(tmp_path: Path) -> None:
    cfg = _load_config(tmp_path / "config.toml", "")
    assert cfg.render_browser_max_concurrency == 0
    assert cfg.render_browser_executable_path == ""
    assert cfg.render_long_image_default_width == 900
    assert cfg.render_long_image_default_padding == 28


def test_render_config_accepts_custom_value(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[render]
browser_max_concurrency = 4
browser_executable_path = "/opt/chrome/chrome"
long_image_default_width = 1080
long_image_default_padding = 36
""",
    )
    assert cfg.render_browser_max_concurrency == 4
    assert cfg.render_browser_executable_path == "/opt/chrome/chrome"
    assert cfg.render_long_image_default_width == 1080
    assert cfg.render_long_image_default_padding == 36


def test_render_config_invalid_values_fallback_to_auto(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[render]
browser_max_concurrency = -3
long_image_default_width = -1
long_image_default_padding = 999
""",
    )
    assert cfg.render_browser_max_concurrency == 0
    assert cfg.render_long_image_default_width == 320
    assert cfg.render_long_image_default_padding == 159


def test_prompt_system_info_defaults_to_disabled(tmp_path: Path) -> None:
    cfg = _load_config(tmp_path / "config.toml", "")

    assert cfg.prompt_system_info.enabled is False
    assert cfg.prompt_system_info.show_os is True
    assert cfg.prompt_system_info.show_network is True
    assert cfg.prompt_system_info.show_process is True


def test_prompt_system_info_custom_switches(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[prompt.system_info]
enabled = true
show_network = false
show_disks = false
show_process = false
""",
    )

    assert cfg.prompt_system_info.enabled is True
    assert cfg.prompt_system_info.show_os is True
    assert cfg.prompt_system_info.show_network is False
    assert cfg.prompt_system_info.show_disks is False
    assert cfg.prompt_system_info.show_process is False
