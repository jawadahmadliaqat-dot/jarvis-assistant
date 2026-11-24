"""Proactive-alert tool — ask Jarvis what needs attention right now.

This is the explicit version of the background checker (core/proactive):
when the user asks, quiet hours do NOT suppress the result.
"""

from __future__ import annotations

from typing import Any

from core.proactive import ProactiveChecker
from tools.registry import Tool, ToolRegistry


def register(registry: ToolRegistry, context: dict[str, Any]) -> None:
    def _check() -> str:
        checker = ProactiveChecker(
            context["config"], context["memory"],
            tasks=context.get("tasks"),
        )
        alerts = checker.check(respect_quiet_hours=False)
        if not alerts:
            return "Nothing needs your attention right now."
        return "\n".join(alerts)

    registry.register(
        Tool(
            name="check_alerts",
            description="Check for anything needing attention: due reminders, low disk, finished background tasks.",
            parameters={"type": "object", "properties": {}},
            func=_check,
        )
    )
