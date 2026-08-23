"""Condition-driven automation workflows."""

from Undefined.automations.constants import (
    DEFAULT_LOOP_MAX_ITERATIONS,
    SELF_CALL_TOOL_NAME,
)
from Undefined.automations.match import AutomationEvent
from Undefined.automations.storage import AutomationStorage

__all__ = [
    "AutomationEvent",
    "AutomationStorage",
    "DEFAULT_LOOP_MAX_ITERATIONS",
    "SELF_CALL_TOOL_NAME",
]
