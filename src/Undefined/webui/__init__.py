from __future__ import annotations


def run() -> None:
    # 延迟导入，避免 `Undefined.webui` 过早加载
    from .app import run as _run

    _run()


__all__ = ["run"]
