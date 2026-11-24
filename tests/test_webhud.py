"""Web HUD tests — stdlib server on an ephemeral port, no keys, no network
(except the briefing's own weather/news calls, which degrade honestly).

Run from the project root:
    python -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)


def _brain_fixture(tmpdir):
    """Offline Brain + TaskManager, same shape as test_smoke.py."""
    from core.brain import Brain
    from core.config import Config
    from core.memory import Memory
    from core.tasks import TaskManager
    from tools.registry import ToolRegistry, load_all_tools

    config = Config({})
    config._data["paths"]["data_dir"] = tmpdir
    mem = Memory(Path(tmpdir))
    registry = ToolRegistry()
    ctx = {"config": config, "memory": mem, "data_dir": Path(tmpdir)}
    load_all_tools(registry, ctx)
    brain = Brain(config, mem, registry)
    tasks = TaskManager(Path(tmpdir))
    brain.task_manager = tasks
    return brain, config, tasks, mem


class WebHudTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from gui.webserver import WebHUD, create_server

        self.brain, self.config, self.tasks, self.mem = _brain_fixture(
            self.tmp.name
        )
        # speak=False: tests stay hermetic (no TTS subprocesses).
        self.hud = WebHUD(self.brain, self.config, tasks=self.tasks, speak=False)
        self.server = create_server(self.hud, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.mem.close()
        self.tmp.cleanup()

    # -- http helpers -------------------------------------------------------
    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path):
        with urllib.request.urlopen(self._url(path), timeout=10) as r:
            return r.status, r.read()

    def _post(self, path, payload):
        req = urllib.request.Request(
            self._url(path),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()

    # -- tests ---------------------------------------------------------------
    def test_index_serves_html_with_panels(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        for panel_id in (
            "systems", "status", "tasks", "voice-panel", "comms",
            "controls", "command-input", "face", "waveform",
            "state-badge", "clock",
        ):
            self.assertIn(f'id="{panel_id}"', text)
        self.assertIn("JARVIS", text)

    def test_static_assets(self):
        status, body = self._get("/style.css")
        self.assertEqual(status, 200)
        self.assertIn(b"--teal", body)
        status, body = self._get("/app.js")
        self.assertEqual(status, 200)
        self.assertIn(b"/api/state", body)

    def test_state_shape(self):
        status, body = self._get("/api/state")
        self.assertEqual(status, 200)
        data = json.loads(body)
        for key in (
            "state", "provider", "cpu", "memory", "disk", "gpu",
            "uptime", "processes", "platform", "voice_muted", "tasks",
        ):
            self.assertIn(key, data)
        self.assertEqual(data["state"], "IDLE")
        self.assertEqual(data["provider"], "offline")
        self.assertIsInstance(data["tasks"], list)
        self.assertIsInstance(data["voice_muted"], bool)
        for key in ("cpu", "memory", "disk"):
            self.assertTrue(
                data[key] is None or isinstance(data[key], (int, float)),
                f"{key} should be a number or None",
            )
            if isinstance(data[key], (int, float)):
                self.assertGreaterEqual(data[key], 0)
                self.assertLessEqual(data[key], 100)

    def test_command_offline_calculate(self):
        status, body = self._post("/api/command", {"text": "calculate 12 * 8"})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("96", data["reply"])
        # The exchange is in the log, and state settles back to IDLE.
        _, log_body = self._get("/api/log")
        log = json.loads(log_body)["log"]
        self.assertTrue(any("12 * 8" in e["text"] for e in log))
        self.assertTrue(any("96" in e["text"] for e in log))
        _, state_body = self._get("/api/state")
        self.assertEqual(json.loads(state_body)["state"], "IDLE")

    def test_briefing_returns_text(self):
        status, body = self._post("/api/briefing", {})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("text", data)
        self.assertTrue(isinstance(data["text"], str) and data["text"].strip())

    def test_tasks_and_mute(self):
        status, body = self._get("/api/tasks")
        self.assertEqual(status, 200)
        self.assertIn("tasks", json.loads(body))

        status, body = self._post("/api/mute", {"muted": True})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["muted"])
        _, state_body = self._get("/api/state")
        self.assertTrue(json.loads(state_body)["voice_muted"])

        status, body = self._post("/api/mute", {"muted": False})
        self.assertFalse(json.loads(body)["muted"])

    def test_listen_sets_state(self):
        status, body = self._post("/api/listen", {"active": True})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["state"], "LISTENING")
        status, body = self._post("/api/listen", {"active": False})
        self.assertEqual(json.loads(body)["state"], "IDLE")

    def test_unknown_routes_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/nope")
        self.assertEqual(ctx.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/api/nope", {})
        self.assertEqual(ctx.exception.code, 404)

    def test_empty_command_refused_politely(self):
        status, body = self._post("/api/command", {"text": "   "})
        self.assertEqual(status, 200)
        self.assertIn("didn't hear", json.loads(body)["reply"])


if __name__ == "__main__":
    unittest.main()
