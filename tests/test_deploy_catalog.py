"""部署目录（catalog）与镜像引用（images）的一致性测试。

这些断言把「设计约定」变成可执行约束：新增服务时若漏了端口或模板，测试先失败。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from Undefined.deploy import catalog, images

TEMPLATE_DIR = Path(catalog.__file__).resolve().parent / "templates"

#: 期望的服务集合与默认选项——改动这些默认值时必须同步测试，防止悄悄变更行为。
EXPECTED_OPTIONAL_SERVICES = ("searxng", "firecrawl", "lxmusic2api")
EXPECTED_REQUIRED_SERVICES = ("napcat",)
EXPECTED_PORT_DEFAULTS = {
    "bot_api": 8788,
    "bot_webui": 8787,
    "firecrawl": 3002,
    "lxmusic2api": 3000,
    "napcat_webui": 6099,
    "napcat_ws": 3001,
    "searxng": 8080,
}


def test_optional_services_are_stable() -> None:
    assert tuple(s.key for s in catalog.OPTIONAL_SERVICES) == EXPECTED_OPTIONAL_SERVICES
    assert tuple(s.key for s in catalog.REQUIRED_SERVICES) == EXPECTED_REQUIRED_SERVICES


def test_napcat_is_not_optional() -> None:
    """NapCat 是必需的协议端，不能出现在可选列表里，否则向导会允许不部署它。"""
    assert catalog.NAPCAT.key not in {
        service.key for service in catalog.OPTIONAL_SERVICES
    }


def test_port_defaults_match_contract() -> None:
    assert catalog.port_defaults() == EXPECTED_PORT_DEFAULTS


def test_port_keys_are_unique_across_services() -> None:
    seen: dict[str, str] = {}
    for service in (*catalog.REQUIRED_SERVICES, *catalog.OPTIONAL_SERVICES):
        for spec in service.ports:
            assert spec.key not in seen, (
                f"端口键 {spec.key} 同时属于 {seen.get(spec.key)} 与 {service.key}"
            )
            seen[spec.key] = service.key

    for spec in catalog.BOT_PORTS:
        assert spec.key not in seen, f"本体端口键 {spec.key} 与服务端口冲突"


def test_port_env_var_names_are_unique() -> None:
    """``.env`` 变量名由端口键派生，重名会让两个端口互相覆盖。"""
    names = [spec.env_var for spec in catalog.port_specs().values()] + [
        spec.bind_env_var for spec in catalog.port_specs().values()
    ]
    assert len(names) == len(set(names))


def test_compose_fragments_exist() -> None:
    for service in (*catalog.REQUIRED_SERVICES, *catalog.OPTIONAL_SERVICES):
        assert (TEMPLATE_DIR / service.compose_fragment).is_file(), (
            f"{service.key} 引用的模板 {service.compose_fragment} 不存在"
        )


def test_shared_templates_exist() -> None:
    for name in (
        "compose.base.yaml",
        "compose.bot.yaml",
        "Dockerfile.bot",
        ".dockerignore",
        "searxng.settings.yml",
        "lxmusic2api.config.toml",
    ):
        assert (TEMPLATE_DIR / name).is_file(), f"缺少模板 {name}"


def test_selected_service_rejects_unknown_key() -> None:
    with pytest.raises(KeyError) as excinfo:
        catalog.selected_service("nope")
    # 报错信息要列出可选值，方便用户直接改参数
    assert "searxng" in str(excinfo.value)


@pytest.mark.parametrize("mode", catalog.DEPLOY_MODES)
def test_deploy_modes_are_exhaustive(mode: str) -> None:
    assert mode in ("container", "host")


def test_vendor_images_are_pinned() -> None:
    """第三方镜像必须 pin 到具体 tag：只有 latest 的项需显式登记。"""
    allowed_floating = {
        "firecrawl_playwright",
        "firecrawl_postgres",
    }
    for key, reference in images.vendor_images().items():
        assert ":" in reference, f"{key} 缺少 tag：{reference}"
        tag = reference.rsplit(":", 1)[1]
        if tag == "latest":
            assert key in allowed_floating, (
                f"{key} 使用 latest 但不在允许清单内，请 pin 到具体版本"
            )


def test_lxmusic2api_pin_is_full_sha() -> None:
    # 上游没有 tag/release，只能锚定 commit，且必须是完整 sha 才能复现构建
    assert images.short_sha(images.LXMUSIC2API_UPSTREAM_SHA) == (
        images.LXMUSIC2API_UPSTREAM_SHA[:7].lower()
    )
    assert images.LXMUSIC2API_UPSTREAM_REPO.endswith(".git")


def test_short_sha_rejects_invalid_input() -> None:
    with pytest.raises(ValueError):
        images.short_sha("main")


def test_image_owner_resolution_order() -> None:
    assert images.resolve_image_owner({"UNDEFINED_DEPLOY_IMAGE_OWNER": "a"}) == "a"
    assert images.resolve_image_owner({"GITHUB_REPOSITORY_OWNER": "b"}) == "b"
    assert images.resolve_image_owner({"GITHUB_REPOSITORY": "c/repo"}) == "c"
    assert images.resolve_image_owner({}) == images.DEFAULT_IMAGE_OWNER


def test_bot_image_uses_v_prefixed_tag() -> None:
    reference = images.bot_image("owner", "1.2.3")
    assert reference.reference == "ghcr.io/owner/undefined-bot:v1.2.3"


def test_project_version_falls_back_to_dev(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pyproject 与包元数据都拿不到时回退 dev，而不是抛异常中断部署。"""
    import importlib.metadata

    def _missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _missing)
    assert images.resolve_project_version(tmp_path) == images.DEV_VERSION


def test_project_version_reads_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "9.9.9"\n', encoding="utf-8"
    )
    assert images.resolve_project_version(tmp_path) == "9.9.9"


def test_project_version_ignores_broken_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project\n", encoding="utf-8")
    # 解析失败时回退到包元数据（本仓已安装），不应抛出
    assert images.resolve_project_version(tmp_path)
