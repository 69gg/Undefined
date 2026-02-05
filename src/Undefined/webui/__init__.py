from __future__ import annotations


def run() -> None:
    # Lazy import to keep `Undefined.webui` lightweight.
    from .app import run as _run

    _run()


__all__ = ["run"]
