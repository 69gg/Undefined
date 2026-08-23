"""Compatibility imports for the automation runtime.

Prefer ``Undefined.automations.service.AutomationService``.
"""

from Undefined.automations.address import resolve_task_address as _resolve_task_address
from Undefined.automations.constants import SELF_CALL_TOOL_NAME
from Undefined.automations.service import AutomationService as TaskScheduler

__all__ = ["SELF_CALL_TOOL_NAME", "TaskScheduler", "_resolve_task_address"]
