"""Morning briefing — time, weather, due reminders, news headlines,
notes count. Runs at startup in voice mode and on demand.
"""

from __future__ import annotations

import datetime
from typing import Any

from tools.registry import Tool, ToolRegistry
from tools.search import search_news
from tools.timecalc import get_date, get_time
from tools.weather import get_weather


def morning_briefing(context: dict[str, Any]) -> str:
    config = context["config"]
    memory = context["memory"]
    parts = [f"Good morning, {config.owner}. {get_time(context)}"]
    parts.append(get_weather(config.city))
    due = memory.due_reminders()
    pending = memory.list_reminders()
    if due:
        parts.append("Due reminders:")
        parts.extend(f"  - {r['text']}" for r in due)
        for r in due:
            memory.mark_reminder_done(r["id"])
    elif pending:
        parts.append(f"You have {len(pending)} pending reminder(s).")
    notes_count = 0
    try:
        from tools.notes import _load as _load_notes

        notes_count = len(_load_notes(context))
    except Exception:
        pass
    if notes_count:
        parts.append(f"You have {notes_count} saved note(s).")
    try:
        news = search_news("", count=3)
        parts.append("Top headlines:\n" + news)
    except Exception:
        pass
    return "\n".join(parts)


def register(registry: ToolRegistry, context: dict[str, Any]) -> None:
    registry.register(
        Tool(
            name="morning_briefing",
            description="Morning briefing: time, weather, reminders, headlines.",
            parameters={"type": "object", "properties": {}},
            func=lambda: morning_briefing(context),
        )
    )
