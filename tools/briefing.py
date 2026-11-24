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


def evening_summary(context: dict[str, Any]) -> str:
    """Evening day-summary: what happened today, what is still open.

    Only counts things that are actually recorded — nothing is guessed.
    """
    config = context["config"]
    memory = context["memory"]
    now = datetime.datetime.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    parts = [f"Good evening, {config.owner}. {get_time(context)}"]
    turns = memory.messages_since(day_start)
    if turns:
        parts.append(f"We had {turns} message(s) today.")
    done_today = memory.reminders_completed_since(day_start)
    if done_today:
        parts.append(f"Reminders completed today: {done_today}.")
    pending = memory.list_reminders()
    if pending:
        parts.append(f"Still pending ({len(pending)}):")
        parts.extend(f"  - {r['text']}" for r in pending[:5])
        if len(pending) > 5:
            parts.append(f"  …and {len(pending) - 5} more.")
    else:
        parts.append("No pending reminders — a clean slate.")
    tasks = context.get("tasks")
    if tasks is not None:
        items = [t for t in tasks.list_tasks()
                 if t.get("status") in ("running", "queued")]
        done_items = [t for t in tasks.list_tasks()
                      if t.get("status") == "done"
                      and (t.get("updated_at") or 0) >= day_start]
        if done_items:
            parts.append(
                "Background tasks finished today: "
                + ", ".join(t["description"] for t in done_items[:3]) + "."
            )
        if items:
            parts.append(
                f"{len(items)} background task(s) still running."
            )
    try:
        from tools.notes import _load as _load_notes

        notes_count = len(_load_notes(context))
    except Exception:
        notes_count = 0
    if notes_count:
        parts.append(f"You have {notes_count} saved note(s).")
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
    registry.register(
        Tool(
            name="evening_summary",
            description="Evening day-summary: today's messages, reminders done/pending, tasks.",
            parameters={"type": "object", "properties": {}},
            func=lambda: evening_summary(context),
        )
    )
