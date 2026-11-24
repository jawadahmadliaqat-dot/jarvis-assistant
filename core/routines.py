"""Routines — named, scheduled sets of actions.

A routine is a small schedule from config:

    routines:
      definitions:
        - name: morning
          time: "07:00"
          actions:
            - {tool: morning_briefing}
        - name: evening
          time: "21:30"
          actions:
            - {tool: evening_summary}

Actions are tool calls (``{tool: <name>, args: {...}}``) or a plain
``{speak: <text>}`` line. A routine is "due" when its time has passed
today and it has not run yet today (tracked in routines_state.json in
the data dir). Running is explicit — nothing runs by itself unless the
user starts Jarvis with --routine or the voice loop's scheduler calls it.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

DEFAULT_DEFINITIONS = [
    {"name": "morning", "time": "07:00",
     "actions": [{"tool": "morning_briefing"}]},
    {"name": "evening", "time": "21:30",
     "actions": [{"tool": "evening_summary"}]},
]


class RoutineRunner:
    def __init__(self, config, registry, context: dict[str, Any],
                 logger: logging.Logger | None = None):
        self.config = config
        self.registry = registry
        self.context = context
        self.logger = logger or logging.getLogger("jarvis.routines")
        self.data_dir = Path(config.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "routines_state.json"

    # -- definitions ------------------------------------------------------
    def definitions(self) -> list[dict[str, Any]]:
        defs = self.config.get("routines", "definitions", default=None)
        if not defs:
            return [dict(d) for d in DEFAULT_DEFINITIONS]
        out = []
        for d in defs:
            if isinstance(d, dict) and d.get("name") and d.get("time"):
                out.append({
                    "name": str(d["name"]),
                    "time": str(d["time"]),
                    "actions": list(d.get("actions") or []),
                })
        return out or [dict(d) for d in DEFAULT_DEFINITIONS]

    def get(self, name: str) -> dict[str, Any] | None:
        for d in self.definitions():
            if d["name"].lower() == name.lower():
                return d
        return None

    def list_routines(self) -> str:
        defs = self.definitions()
        if not defs:
            return "No routines configured."
        lines = ["Routines:"]
        for d in defs:
            acts = ", ".join(
                a.get("tool", a.get("speak", "?")) if isinstance(a, dict) else str(a)
                for a in d["actions"]
            )
            lines.append(f"  - {d['name']} at {d['time']}: {acts or 'no actions'}")
        return "\n".join(lines)

    # -- due tracking ------------------------------------------------------
    def _load_state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"last_run": {}}

    def _save_state(self, state: dict[str, Any]) -> None:
        tmp = self.state_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def due_routines(self, now: datetime.datetime | None = None) -> list[dict[str, Any]]:
        """Routines whose time has passed today and that have not run today."""
        now = now or datetime.datetime.now()
        today = now.strftime("%Y-%m-%d")
        state = self._load_state()
        last_run = state.get("last_run", {})
        due = []
        for d in self.definitions():
            try:
                hour, minute = (int(x) for x in d["time"].split(":"))
                when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            except (ValueError, AttributeError):
                continue
            if when <= now and last_run.get(d["name"]) != today:
                due.append(d)
        return due

    def mark_run(self, name: str, day: str | None = None) -> None:
        day = day or datetime.datetime.now().strftime("%Y-%m-%d")
        state = self._load_state()
        state.setdefault("last_run", {})[name] = day
        self._save_state(state)

    # -- execution ----------------------------------------------------------
    def run(self, name: str) -> str:
        definition = self.get(name)
        if definition is None:
            known = ", ".join(d["name"] for d in self.definitions())
            return f"No routine called '{name}'. Available: {known}."
        parts: list[str] = []
        for action in definition["actions"]:
            if not isinstance(action, dict):
                continue
            if "tool" in action:
                tool = str(action["tool"])
                args = action.get("args") or {}
                if not isinstance(args, dict):
                    args = {}
                result = self.registry.execute(tool, args)
                parts.append(result)
            elif "speak" in action:
                parts.append(str(action["speak"]))
        self.mark_run(definition["name"])
        self.logger.info("routine %s ran", definition["name"])
        return "\n".join(p for p in parts if p) or f"Routine '{name}' ran (no output)."
