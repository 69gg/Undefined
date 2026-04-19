"""Local admin management (config.local.json)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

LOCAL_CONFIG_PATH = Path("config.local.json")


def load_local_admins() -> list[int]:
    """从本地配置文件加载动态管理员列表"""
    if not LOCAL_CONFIG_PATH.exists():
        return []
    try:
        with open(LOCAL_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        admin_qqs: list[int] = data.get("admin_qqs", [])
        return admin_qqs
    except Exception as exc:
        logger.warning("读取本地配置失败: %s", exc)
        return []


def save_local_admins(admin_qqs: list[int]) -> None:
    """保存动态管理员列表到本地配置文件"""
    try:
        data: dict[str, list[int]] = {}
        if LOCAL_CONFIG_PATH.exists():
            with open(LOCAL_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

        data["admin_qqs"] = admin_qqs

        with open(LOCAL_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info("已保存管理员列表到 %s", LOCAL_CONFIG_PATH)
    except Exception as exc:
        logger.error("保存本地配置失败: %s", exc)
        raise
