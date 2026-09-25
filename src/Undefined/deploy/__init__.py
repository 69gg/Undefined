"""一次性容器化部署入口（``uv run deploy``）。

本包只负责“把本体与依赖服务用 Docker Compose 跑起来”，不参与运行时逻辑。
对外只暴露 :func:`main`，实现按职责拆分在 ``catalog`` / ``generate`` /
``config_patch`` / ``nagaagent`` / ``state`` / ``docker_cli`` / ``cli`` 中。
"""

from __future__ import annotations

from .cli import main

__all__ = ["main"]
