"""Example plugin: countdown timers.

start_timer(seconds, label) starts a background timer; list_timers shows
running and finished timers. Timers survive only for this session — for
persistent reminders use the built-in add_reminder tool instead.
"""

import threading
import time

from tools.registry import Tool

_TIMERS: dict[str, dict] = {}
_LOCK = threading.Lock()


def start_timer(seconds: int, label: str = "timer") -> str:
    seconds = max(1, int(seconds))
    end = time.time() + seconds

    def _fire():
        with _LOCK:
            _TIMERS[label] = {"status": "finished", "ends_at": end}

    timer = threading.Timer(seconds, _fire)
    timer.daemon = True
    timer.start()
    with _LOCK:
        _TIMERS[label] = {"status": "running", "ends_at": end}
    return f"Timer '{label}' started for {seconds} seconds."


def list_timers() -> str:
    with _LOCK:
        items = dict(_TIMERS)
    if not items:
        return "No timers."
    lines = []
    for label, info in items.items():
        if info["status"] == "running":
            left = max(0, int(info["ends_at"] - time.time()))
            lines.append(f"{label}: running, {left}s left")
        else:
            lines.append(f"{label}: finished ⏰")
    return "\n".join(lines)


TOOLS = [
    Tool(
        name="start_timer",
        description="Start a countdown timer (seconds, optional label).",
        parameters={
            "type": "object",
            "properties": {
                "seconds": {"type": "integer"},
                "label": {"type": "string"},
            },
            "required": ["seconds"],
        },
        func=start_timer,
    ),
    Tool(
        name="list_timers",
        description="List running and finished timers.",
        parameters={"type": "object", "properties": {}},
        func=list_timers,
    ),
]
