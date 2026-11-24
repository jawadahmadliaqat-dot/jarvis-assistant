"""Web HUD — a Mark 57-style browser interface for Jarvis.

Stdlib only (``http.server``), no new dependencies, no PyQt6 needed.
Binds 127.0.0.1 so the page is reachable only from this machine.
Serves the page in ``gui/web/`` plus JSON endpoints that drive it.

Works with zero API keys (offline mode), exactly like the CLI: the
command endpoint runs the same Brain tool-use loop as text mode.

Endpoints:
  GET  /              the HUD page
  GET  /style.css     stylesheet
  GET  /app.js        frontend logic
  GET  /api/state    live state + system gauges + tasks
  GET  /api/log      recent log lines
  GET  /api/tasks    background tasks
  POST /api/command  {"text": ...} -> {"reply": ...} (real Brain reply)
  POST /api/briefing -> {"text": ...} (morning briefing)
  POST /api/mute     {"muted": bool} -> {"muted": bool}
  POST /api/listen   {"active": bool} -> {"state": ...} (hold-to-talk badge)
"""

from __future__ import annotations

import datetime
import json
import platform
import shutil
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

WEB_DIR = Path(__file__).resolve().parent / "web"
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 64 * 1024
LOG_KEEP = 200

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

STATES = ("IDLE", "LISTENING", "THINKING", "SPEAKING")


def _gpu_percent() -> int | None:
    """GPU utilisation via nvidia-smi when present, else None (honest N/A)."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode != 0:
            return None
        return max(0, min(100, int(out.stdout.strip().splitlines()[0])))
    except Exception:
        return None


def _metrics() -> dict[str, Any]:
    """Live system numbers; missing pieces stay None (shown as N/A)."""
    out: dict[str, Any] = {
        "cpu": None, "memory": None, "disk": None, "gpu": None,
        "uptime": None, "processes": None,
    }
    try:
        import psutil  # type: ignore

        out["cpu"] = round(psutil.cpu_percent(interval=None))
        out["memory"] = round(psutil.virtual_memory().percent)
        out["disk"] = round(psutil.disk_usage("/").percent)
        out["uptime"] = int(time.time() - psutil.boot_time())
        out["processes"] = len(psutil.pids())
    except Exception:
        pass
    out["gpu"] = _gpu_percent()
    return out


class WebHUD:
    """Shared state between the HTTP handler and the Brain."""

    def __init__(self, brain, config, tasks=None, speak: bool = True):
        self.brain = brain
        self.config = config
        self.tasks = tasks
        self.speak = speak
        self.state = "IDLE"
        self.voice_muted = False
        self.started_at = time.time()
        self._lock = threading.Lock()       # serialises Brain use
        self._state_lock = threading.Lock()
        self._log: deque[dict[str, str]] = deque(maxlen=LOG_KEEP)
        self._tts = None
        self._gpu_cache: tuple[float, int | None] = (0.0, None)
        self.log("SYS", "Jarvis online.")
        self.log("SYS", f"Provider: {brain.active_provider_name}.")

    # -- log ---------------------------------------------------------------
    def log(self, tag: str, text: str) -> None:
        self._log.append({
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "tag": tag,
            "text": text,
        })

    def log_lines(self) -> list[dict[str, str]]:
        return list(self._log)

    # -- state ---------------------------------------------------------------
    def set_state(self, state: str) -> None:
        if state not in STATES:
            return
        with self._state_lock:
            self.state = state

    # -- metrics ---------------------------------------------------------------
    def state_dict(self) -> dict[str, Any]:
        metrics = _metrics()
        # Cache the GPU probe (nvidia-smi spawns a process) for 10 s.
        now = time.time()
        if now - self._gpu_cache[0] > 10:
            self._gpu_cache = (now, metrics["gpu"])
        else:
            metrics["gpu"] = self._gpu_cache[1]
        tasks = []
        if self.tasks is not None:
            try:
                tasks = [
                    {
                        "id": t.get("id", ""),
                        "description": t.get("description", ""),
                        "status": t.get("status", ""),
                        "progress": t.get("progress", ""),
                    }
                    for t in self.tasks.list_tasks()
                ]
            except Exception:
                tasks = []
        with self._state_lock:
            state = self.state
        return {
            "state": state,
            "provider": self.brain.active_provider_name,
            "cpu": metrics["cpu"],
            "memory": metrics["memory"],
            "disk": metrics["disk"],
            "gpu": metrics["gpu"],
            "uptime": metrics["uptime"],
            "processes": metrics["processes"],
            "platform": (
                f"{platform.system()} {platform.release()} "
                f"({platform.machine()})"
            ),
            "voice_muted": self.voice_muted,
            "tasks": tasks,
        }

    # -- actions ---------------------------------------------------------------
    def handle_command(self, text: str) -> str:
        """Run one command through the real Brain; returns its reply."""
        text = (text or "").strip()
        if not text:
            return "I didn't hear anything, sir."
        self.set_state("THINKING")
        self.log("YOU", text)
        with self._lock:
            reply = self.brain.respond(text)
        self.log("JARVIS", reply)
        if self.speak and not self.voice_muted:
            self._speak_async(reply)
        else:
            self.set_state("IDLE")
        return reply

    def run_briefing(self) -> str:
        with self._lock:
            text = self.brain.tool_result_text("morning_briefing", {})
        self.log("JARVIS", text)
        return text

    def set_muted(self, muted: bool) -> bool:
        self.voice_muted = bool(muted)
        self.log("SYS", f"Voice {'muted' if muted else 'unmuted'}.")
        return self.voice_muted

    def set_listening(self, active: bool) -> str:
        with self._state_lock:
            if self.state in ("THINKING", "SPEAKING"):
                return self.state
            self.state = "LISTENING" if active else "IDLE"
            return self.state

    # -- voice ---------------------------------------------------------------
    def _get_tts(self):
        if self._tts is None:
            try:
                from voice.tts import TTS

                self._tts = TTS(
                    engine=self.config.get("voice", "tts_engine", default="auto")
                )
            except Exception:
                self._tts = False
        return self._tts or None

    def _speak_async(self, text: str) -> None:
        tts = self._get_tts()
        if tts is None:
            self.set_state("IDLE")
            return
        self.set_state("SPEAKING")

        def _work() -> None:
            try:
                tts.speak(text)
            except Exception:
                pass
            finally:
                self.set_state("IDLE")

        threading.Thread(target=_work, daemon=True, name="webhud-tts").start()


# -- HTTP plumbing ------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "JarvisWebHUD/1.0"

    @property
    def hud(self) -> WebHUD:
        return self.server.hud  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    # -- helpers ---------------------------------------------------------------
    def _send_json(self, status: int, obj: Any) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            self._send_json(404, {"error": "not found"})
            return
        self.send_response(200)
        self.send_header(
            "Content-Type", MIME.get(path.suffix, "application/octet-stream")
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0 or length > MAX_BODY_BYTES:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (ValueError, UnicodeDecodeError):
            return {}

    # -- routes ---------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        if self.path in ("/", "/index.html"):
            self._send_file(WEB_DIR / "index.html")
            return
        if self.path in ("/style.css", "/app.js"):
            # Static assets only ever come from gui/web/ — no traversal.
            name = self.path.lstrip("/")
            target = (WEB_DIR / name).resolve()
            if target.parent != WEB_DIR.resolve() or not target.is_file():
                self._send_json(404, {"error": "not found"})
                return
            self._send_file(target)
            return
        if self.path == "/api/state":
            self._send_json(200, self.hud.state_dict())
            return
        if self.path == "/api/log":
            self._send_json(200, {"log": self.hud.log_lines()})
            return
        if self.path == "/api/tasks":
            tasks = self.hud.state_dict()["tasks"]
            self._send_json(200, {"tasks": tasks})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        body = self._read_json()
        if self.path == "/api/command":
            reply = self.hud.handle_command(str(body.get("text", "")))
            self._send_json(200, {"reply": reply})
            return
        if self.path == "/api/briefing":
            self._send_json(200, {"text": self.hud.run_briefing()})
            return
        if self.path == "/api/mute":
            muted = self.hud.set_muted(bool(body.get("muted", False)))
            self._send_json(200, {"muted": muted})
            return
        if self.path == "/api/listen":
            state = self.hud.set_listening(bool(body.get("active", False)))
            self._send_json(200, {"state": state})
            return
        self._send_json(404, {"error": "not found"})


def create_server(hud: WebHUD, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """Build the server (not started). Port 0 picks an ephemeral port."""
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    server.daemon_threads = True
    server.hud = hud  # type: ignore[attr-defined]
    return server


def run_web_hud(brain, config, tasks=None, port: int = DEFAULT_PORT) -> int:
    """Serve the web HUD until Ctrl+C. Returns the process exit code."""
    hud = WebHUD(
        brain, config, tasks=tasks,
        speak=bool(config.get("voice", "speak_replies", default=True)),
    )
    server = create_server(hud, port)
    actual_port = server.server_address[1]
    print(f"Jarvis web HUD: http://127.0.0.1:{actual_port}", flush=True)
    print(
        f"Provider: {brain.active_provider_name} — open the URL in your browser.",
        flush=True,
    )
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb HUD stopped. Goodbye, sir.")
    finally:
        server.shutdown()
        server.server_close()
    return 0
