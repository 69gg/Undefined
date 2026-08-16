"""Resolve the automation runtime injected into skill context."""

from typing import Any


def get_automation_service(context: dict[str, Any]) -> Any | None:
    service = context.get("automations")
    if service is not None:
        return service
    return context.get("scheduler")
