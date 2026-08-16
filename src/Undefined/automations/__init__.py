"""Condition-driven automation workflows."""

from Undefined.automations.constants import SELF_CALL_TOOL_NAME, LOOP_MAX_ITERATIONS
from Undefined.automations.match import AutomationEvent
from Undefined.automations.storage import AutomationStorage

__all__ = [
    "AutomationEvent",
    "AutomationStorage",
    "LOOP_MAX_ITERATIONS",
    "SELF_CALL_TOOL_NAME",
]
