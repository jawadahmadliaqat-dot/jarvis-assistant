"""Live context for the brain — what is actually true right now.

Jarvis injects a short, honest "live context" block into the system
prompt on every turn: time of day, system load, the active window (when
it can be detected), pending reminders. Only things that were actually
detected are included — nothing is guessed. Detection is best-effort
and cross-platform; when something cannot be detected it is simply
left out of the block.
"""

from __future__ import annotations

import datetime
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _tz(config) -> datetime.tzinfo:
    name = config.timezone if config is not None else "Asia/Karachi"
    try:
        return ZoneInfo(name)
    except Exception:
        return datetime.timezone.utc


def part_of_day(hour: int) -> str:
    if 0 <= hour < 5:
        return "late night"
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 22:
        return "evening"
    return "night"


def in_quiet_hours(config, now: datetime.datetime | None = None) -> bool:
    """True when `now` falls inside config routines.quiet_hours.

    quiet_hours is [start, end] as "HH:MM" strings; a window that
    crosses midnight (e.g. 23:00 -> 07:00) is handled.
    """
    try:
        start_s, end_s = config.get(
            "routines", "quiet_hours", default=["23:00", "07:00"]
        )
        start = datetime.datetime.strptime(start_s, "%H:%M").time()
        end = datetime.datetime.strptime(end_s, "%H:%M").time()
        current = (now or datetime.datetime.now()).time()
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end
    except Exception:
        return False


def _active_window() -> str | None:
    """Best-effort foreground-window title, or None if undetectable."""
    try:
        if sys.platform.startswith("win"):
            import ctypes

            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return None
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return None
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            return title or None
        if shutil.which("xdotool"):
            out = subprocess.run(
                ["xdotool", "getwindowfocus", "getwindowname"],
                capture_output=True, text=True, timeout=2,
            )
            title = out.stdout.strip()
            return title or None
    except Exception:
        pass
    return None


def _system_load() -> dict[str, Any]:
    """CPU/RAM/disk numbers when psutil is available, else {}."""
    try:
        import psutil  # type: ignore

        disk = psutil.disk_usage("/")
        return {
            "cpu_percent": round(psutil.cpu_percent(interval=None)),
            "ram_percent": round(psutil.virtual_memory().percent),
            "disk_free_gb": disk.free // (1024 ** 3),
        }
    except Exception:
        return {}


def gather_context(config, memory, tasks=None,
                   now: datetime.datetime | None = None) -> dict[str, Any]:
    """Collect everything the brain should know about 'right now'."""
    tz = _tz(config)
    now = now or datetime.datetime.now(tz)
    ctx: dict[str, Any] = {
        "now": now,
        "date_str": now.strftime("%A, %Y-%m-%d"),
        "time_str": now.strftime("%H:%M"),
        "part_of_day": part_of_day(now.hour),
        "late_night": 0 <= now.hour < 5,
    }
    ctx.update(_system_load())
    window = _active_window()
    if window:
        ctx["active_window"] = window
    if memory is not None:
        try:
            pending = memory.list_reminders()
            ctx["pending_reminders"] = len(pending)
            if pending:
                first = pending[0]
                due = datetime.datetime.fromtimestamp(
                    first["due_ts"], tz=tz
                ).strftime("%I:%M %p")
                ctx["next_reminder"] = f"{first['text']} (due {due})"
        except Exception:
            pass
    if tasks is not None:
        try:
            running = [
                t for t in tasks.list_tasks()
                if t.get("status") in ("running", "queued")
            ]
            ctx["open_tasks"] = len(running)
        except Exception:
            pass
    return ctx


def render_context_block(ctx: dict[str, Any]) -> str:
    """Render the gathered context as a prompt block (detected items only)."""
    lines = ["Live context (only what was actually detected):"]
    now = ctx.get("now")
    if now is not None:
        lines.append(
            f"- It is {ctx.get('time_str', '')} on {ctx.get('date_str', '')} "
            f"— {ctx.get('part_of_day', '')}."
        )
        if ctx.get("late_night"):
            lines.append("- It is late at night; the user may be up past bedtime.")
    load = []
    if "cpu_percent" in ctx:
        load.append(f"CPU {ctx['cpu_percent']}%")
    if "ram_percent" in ctx:
        load.append(f"RAM {ctx['ram_percent']}% used")
    if "disk_free_gb" in ctx:
        load.append(f"disk {ctx['disk_free_gb']} GB free")
    if load:
        lines.append("- System load: " + ", ".join(load) + ".")
    if ctx.get("active_window"):
        lines.append(f"- Active window: \"{ctx['active_window']}\".")
    if "pending_reminders" in ctx:
        n = ctx["pending_reminders"]
        lines.append(f"- Pending reminders: {n}.")
        if ctx.get("next_reminder"):
            lines.append(f"- Next reminder: {ctx['next_reminder']}.")
    if ctx.get("open_tasks"):
        lines.append(f"- Background tasks running: {ctx['open_tasks']}.")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)
