"""Shared native app metadata for release and version scripts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class NativeApp:
    app_dir: str
    cargo_package: str
    artifact_prefix: str

    @property
    def package_json(self) -> str:
        return f"apps/{self.app_dir}/package.json"

    @property
    def package_lock(self) -> str:
        return f"apps/{self.app_dir}/package-lock.json"

    @property
    def cargo_toml(self) -> str:
        return f"apps/{self.app_dir}/src-tauri/Cargo.toml"

    @property
    def cargo_lock(self) -> str:
        return f"apps/{self.app_dir}/src-tauri/Cargo.lock"

    @property
    def tauri_conf(self) -> str:
        return f"apps/{self.app_dir}/src-tauri/tauri.conf.json"

    def app_root(self, project_root: Path) -> Path:
        return project_root / "apps" / self.app_dir

    def tauri_root(self, project_root: Path) -> Path:
        return self.app_root(project_root) / "src-tauri"


NATIVE_APPS: tuple[NativeApp, ...] = (
    NativeApp(
        app_dir="undefined-console",
        cargo_package="undefined_console",
        artifact_prefix="Undefined-Console",
    ),
    NativeApp(
        app_dir="undefined-chat",
        cargo_package="undefined_chat",
        artifact_prefix="Undefined-Chat",
    ),
)
