"""Reminders — stored in SQLite memory; due ones are announced on
every turn by the brain.
"""

from __future__ import annotations

import datetime
import re
import time
from typing import Any
from zoneinfo import ZoneInfo

from tools.registry import Tool, ToolRegistry


def _tz(context: dict[str, Any]):
    tz_name = context["config"].timezone if context.get("config") else "Asia/Karachi"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return datetime.timezone.utc


def _fmt_ts(context: dict[str, Any], ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, tz=_tz(context)).strftime("%I:%M %p, %b %d")


def _parse_when(context: dict[str, Any], when: str) -> float | None:
    """Parse 'in 30 minutes', 'in 2 hours', 'at 18:30', or 'tomorrow 9:00'."""
    text = (when or "").strip().lower()
    m = re.match(r"in\s+(\d+)\s*(minute|minutes|min|hour|hours|hr|second|seconds)", text)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        seconds = amount * {"minute": 60, "minutes": 60, "min": 60,
                            "hour": 3600, "hours": 3600, "hr": 3600,
                            "second": 1, "seconds": 1}[unit]
        return time.time() + seconds
    m = re.match(r"(?:at\s+)?(\d{1,2}):(\d{2})\s*(am|pm)?\s*(tomorrow)?", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        now = datetime.datetime.now(_tz(context))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if m.group(4) == "tomorrow" or target <= now:
            target += datetime.timedelta(days=1)
        return target.timestamp()
    return None


def add_reminder(context: dict[str, Any], text: str, when: str = "") -> str:
    memory = context["memory"]
    due = _parse_when(context, when) if when else None
    if when and due is None:
        return (
            f"Could not understand when '{when}'. Try 'in 30 minutes' "
            "or 'at 18:30'."
        )
    if due is None:
        due = time.time() + 3600  # default: 1 hour
    rid = memory.add_reminder(text.strip(), due)
    return f"Reminder #{rid} set for {_fmt_ts(context, due)}: {text.strip()}"


def list_reminders(context: dict[str, Any]) -> str:
    rows = context["memory"].list_reminders()
    if not rows:
        return "No pending reminders."
    lines = []
    for r in rows:
        lines.append(f"#{r['id']} [{_fmt_ts(context, r['due_ts'])}]: {r['text']}")
    return "\n".join(lines)


def register(registry: ToolRegistry, context: dict[str, Any]) -> None:
    registry.register(
        Tool(
            name="add_reminder",
            description="Set a reminder. `when` like 'in 30 minutes' or 'at 18:30'.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "when": {"type": "string"},
                },
                "required": ["text"],
            },
            func=lambda text, when="": add_reminder(context, text, when),
        )
    )
    registry.register(
        Tool(
            name="list_reminders",
            description="List pending reminders.",
            parameters={"type": "object", "properties": {}},
            func=lambda: list_reminders(context),
        )
    )
