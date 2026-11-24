"""Persistent background tasks.

Long work (deep research, briefings, ...) runs in a worker thread while
the conversation continues. Tasks are persisted to tasks.json so they
survive a crash or restart: on startup, tasks left `running` are marked
`interrupted` and can be resumed explicitly — nothing re-runs silently.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable


class TaskManager:
    def __init__(self, data_dir: Path, logger: logging.Logger | None = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.file = self.data_dir / "tasks.json"
        self.logger = logger or logging.getLogger("jarvis.tasks")
        self._lock = threading.Lock()
        self._stop_flags: dict[str, threading.Event] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._tasks: list[dict[str, Any]] = self._load()
        # Crash recovery: nothing resumes by itself.
        changed = False
        for t in self._tasks:
            if t["status"] == "running":
                t["status"] = "interrupted"
                t["updated_at"] = time.time()
                changed = True
        if changed:
            self._save()

    # -- persistence -------------------------------------------------------
    def _load(self) -> list[dict[str, Any]]:
        if not self.file.exists():
            return []
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            return list(data.get("tasks", []))
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self) -> None:
        tmp = self.file.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"tasks": self._tasks}, indent=2), encoding="utf-8"
        )
        tmp.replace(self.file)

    # -- CRUD ---------------------------------------------------------------
    def create(self, kind: str, description: str) -> dict[str, Any]:
        task = {
            "id": uuid.uuid4().hex[:8],
            "kind": kind,
            "description": description,
            "status": "queued",
            "progress": "",
            "result": "",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        with self._lock:
            self._tasks.append(task)
            self._save()
        return dict(task)

    def get(self, task_id: str) -> dict[str, Any] | None:
        for t in self._tasks:
            if t["id"] == task_id:
                return dict(t)
        return None

    def list_tasks(self) -> list[dict[str, Any]]:
        return [dict(t) for t in sorted(self._tasks, key=lambda x: x["created_at"])]

    def _update(self, task_id: str, **fields: Any) -> None:
        with self._lock:
            for t in self._tasks:
                if t["id"] == task_id:
                    t.update(fields)
                    t["updated_at"] = time.time()
                    break
            self._save()

    # -- execution -----------------------------------------------------------
    def start(
        self,
        task_id: str,
        runner: Callable[[dict[str, Any], Callable[[str], None], threading.Event], str],
    ) -> bool:
        """Run `runner(task, progress_cb, stop_event)` in a thread.

        The runner returns the final result text. It should call
        progress_cb("...") as it goes and check stop_event periodically.
        """
        task = self.get(task_id)
        if task is None or task["status"] == "running":
            return False
        stop = threading.Event()
        self._stop_flags[task_id] = stop

        def _work() -> None:
            self._update(task_id, status="running", progress="started")
            try:
                result = runner(
                    self.get(task_id) or task,
                    lambda msg: self._update(task_id, progress=msg),
                    stop,
                )
                if stop.is_set():
                    self._update(task_id, status="cancelled", result=result)
                else:
                    self._update(task_id, status="done", result=result, progress="done")
            except Exception as exc:  # noqa: BLE001 - task failure is a status
                self.logger.exception("task %s failed", task_id)
                self._update(task_id, status="failed", result=f"Error: {exc}")

        thread = threading.Thread(target=_work, daemon=True, name=f"task-{task_id}")
        self._workers[task_id] = thread
        thread.start()
        return True

    def stop(self, task_id: str) -> bool:
        flag = self._stop_flags.get(task_id)
        if flag is None:
            return False
        flag.set()
        return True

    def resume(
        self,
        task_id: str,
        runner: Callable[[dict[str, Any], Callable[[str], None], threading.Event], str],
    ) -> bool:
        task = self.get(task_id)
        if task is None or task["status"] not in ("interrupted", "failed", "cancelled"):
            return False
        self._update(task_id, status="queued", progress="resuming")
        return self.start(task_id, runner)
