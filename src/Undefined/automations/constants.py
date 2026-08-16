"""Constants for the automations workflow engine."""

from __future__ import annotations

from pathlib import Path

AUTOMATIONS_FILE_PATH = Path("data/automations.json")
LEGACY_TASKS_FILE_PATH = Path("data/scheduled_tasks.json")

START_NODE_ID = "start"
SELF_CALL_TOOL_NAME = "scheduler.call_self"

CHANNEL_GROUP = "group"
CHANNEL_PRIVATE = "private"
CHANNEL_WECHAT = "wechat"
CHANNELS = frozenset({CHANNEL_GROUP, CHANNEL_PRIVATE, CHANNEL_WECHAT})

START_KINDS = frozenset(
    {
        "message",
        "cron",
        "daily",
        "at",
        "interval",
        "poke",
        "member_join",
        "member_leave",
    }
)
TIME_KINDS = frozenset({"cron", "daily", "at", "interval"})
EVENT_KINDS = frozenset({"message", "poke", "member_join", "member_leave"})

NODE_TYPES = frozenset(
    {
        "start",
        "tool",
        "template",
        "llm.blank",
        "llm.agent",
        "llm.main",
        "branch.if",
        "branch.llm",
        "loop.times",
        "loop.each",
    }
)
STORE_OUTPUT_NODE_TYPES = frozenset({"tool", "llm.blank", "llm.agent", "llm.main"})
RESERVED_VARIABLE_NAMES = frozenset(
    {"trigger", "nodes", "index", "item", "vars", "start", "else"}
)

TEXT_MATCH_MODES = frozenset({"contains", "keyword", "regex"})
PASS_TEXT_MODES = frozenset({"original", "stripped"})

LOOP_MAX_ITERATIONS = 25
DEFAULT_MAX_NODES = 30
DEFAULT_MAX_CONCURRENT = 16
DEFAULT_NODE_TIMEOUT_SECONDS = 600.0
DEFAULT_WORKFLOW_TIMEOUT_SECONDS = 1200.0
DEFAULT_BLANK_LLM_MAX_ITERATIONS = 100
DEFAULT_EVENT_COOLDOWN_SECONDS = 0
DEFAULT_REGEX_TIMEOUT_SECONDS = 0.05

BRANCH_ELSE_CASE = "else"
LOOP_BODY_KIND = "body"
LOOP_EXIT_KIND = "exit"
