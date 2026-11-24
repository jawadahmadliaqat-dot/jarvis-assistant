"""Proactive alerts — things Jarvis notices without being asked.

Triggers (all local, no LLM needed):
  - due reminders the user has not seen yet,
  - disk space running low (config routines.proactive.disk_free_gb_warn),
  - background tasks that finished (done/failed) in the last 24 hours.

Each alert fires ONCE per trigger (deduplicated in
proactive_state.json in the data dir). A low-disk alert re-fires only
after the disk recovers above the threshold and drops low again.
Quiet hours suppress alerts unless the caller explicitly asks
(CLI --check, or the `check_alerts` tool) — unprompted speech never
wakes the user.
"""

from __future__ import annotations

import datetime
import json
import logging
import time
from pathlib import Path
from typing import Any

from core.context import in_quiet_hours

_TASK_ALERT_WINDOW_S = 24 * 3600


def _disk_free_gb() -> float | None:
    try:
        import psutil  # type: ignore

        return psutil.disk_usage("/").free / (1024 ** 3)
    except Exception:
        pass
    try:
        import shutil

        return shutil.disk_usage("/").free / (1024 ** 3)
    except Exception:
        return None


class ProactiveChecker:
    def __init__(self, config, memory, tasks=None,
                 logger: logging.Logger | None = None):
        self.config = config
        self.memory = memory
        self.tasks = tasks
        self.logger = logger or logging.getLogger("jarvis.proactive")
        self.data_dir = Path(config.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "proactive_state.json"

    # -- dedup state -------------------------------------------------------
    def _load_state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"fired": {}}

    def _save_state(self, state: dict[str, Any]) -> None:
        tmp = self.state_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def _fired(self, state: dict[str, Any], key: str) -> bool:
        return key in state.get("fired", {})

    def _mark_fired(self, state: dict[str, Any], key: str) -> None:
        state.setdefault("fired", {})[key] = time.time()

    def _clear_fired(self, state: dict[str, Any], key: str) -> None:
        state.get("fired", {}).pop(key, None)

    # -- checks --------------------------------------------------------------
    def check(self, now: datetime.datetime | None = None,
              respect_quiet_hours: bool = True) -> list[str]:
        """Return new alerts (each at most once per trigger)."""
        now = now or datetime.datetime.now()
        if respect_quiet_hours and in_quiet_hours(self.config, now):
            return []
        state = self._load_state()
        alerts: list[str] = []
        alerts.extend(self._check_reminders(state))
        alerts.extend(self._check_disk(state))
        alerts.extend(self._check_tasks(state))
        self._save_state(state)
        return alerts

    def _check_reminders(self, state: dict[str, Any]) -> list[str]:
        alerts = []
        try:
            due = self.memory.due_reminders()
        except Exception:
            return []
        for r in due:
            key = f"reminder:{r['id']}"
            if self._fired(state, key):
                continue
            alerts.append(f"⏰ Reminder: {r['text']}")
            self._mark_fired(state, key)
        return alerts

    def _check_disk(self, state: dict[str, Any]) -> list[str]:
        warn_gb = float(
            self.config.get("routines", "proactive", "disk_free_gb_warn", default=5)
        )
        free = _disk_free_gb()
        if free is None:
            return []
        if free >= warn_gb:
            self._clear_fired(state, "disk")
            return []
        if self._fired(state, "disk"):
            return []
        self._mark_fired(state, "disk")
        return [
            f"💾 Disk space is low: {free:.1f} GB free "
            f"(warning below {warn_gb:.0f} GB)."
        ]

    def _check_tasks(self, state: dict[str, Any]) -> list[str]:
        if self.tasks is None:
            return []
        alerts = []
        try:
            items = self.tasks.list_tasks()
        except Exception:
            return []
        cutoff = time.time() - _TASK_ALERT_WINDOW_S
        for t in items:
            if t.get("status") not in ("done", "failed"):
                continue
            if (t.get("updated_at") or 0) < cutoff:
                continue
            key = f"task:{t['id']}"
            if self._fired(state, key):
                continue
            status = "finished" if t["status"] == "done" else "failed"
            alerts.append(
                f"🧵 Background task {status}: {t['description']}"
            )
            self._mark_fired(state, key)
        return alerts
