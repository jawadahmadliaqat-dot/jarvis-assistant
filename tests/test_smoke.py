"""Smoke tests — no network, no API keys, no microphone needed.

Run from the project root:
    python -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Keep tests hermetic: no real keys, temp data dir, no network calls
# except where explicitly tolerated (none of these hit the network).
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)


class ConfigTest(unittest.TestCase):
    def test_example_config_loads(self):
        from core.config import load_config

        cfg = load_config(str(ROOT / "config.yaml.example"))
        self.assertEqual(cfg.assistant_name, "Jarvis")
        self.assertIn("gemini", cfg.provider_order)
        self.assertFalse(cfg.api_key("GEMINI_API_KEY"))

    def test_defaults_without_file(self):
        from core.config import Config

        cfg = Config({})
        self.assertEqual(cfg.assistant_name, "Jarvis")
        self.assertEqual(cfg.max_history, 20)
        self.assertTrue(str(cfg.data_dir).endswith(".jarvis"))


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from core.memory import Memory

        self.mem = Memory(Path(self.tmp.name))

    def tearDown(self):
        self.mem.close()
        self.tmp.cleanup()

    def test_facts_round_trip(self):
        self.mem.remember_fact("birthday", "March 2")
        self.assertEqual(self.mem.get_fact("birthday"), "March 2")
        self.assertTrue(self.mem.forget_fact("birthday"))
        self.assertIsNone(self.mem.get_fact("birthday"))

    def test_history_round_trip(self):
        self.mem.add_message("user", "hello")
        self.mem.add_message("assistant", "hi")
        hist = self.mem.recent_history(5)
        self.assertEqual([h["role"] for h in hist], ["user", "assistant"])

    def test_reminders(self):
        import time

        rid = self.mem.add_reminder("call Ali", time.time() - 10)
        self.assertEqual(len(self.mem.due_reminders()), 1)
        self.assertTrue(self.mem.mark_reminder_done(rid))
        self.assertEqual(self.mem.due_reminders(), [])


class ToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from core.config import Config
        from core.memory import Memory
        from tools.registry import ToolRegistry, load_all_tools

        self.config = Config({})
        self.config._data["paths"]["data_dir"] = self.tmp.name
        self.mem = Memory(Path(self.tmp.name))
        self.registry = ToolRegistry()
        self.ctx = {
            "config": self.config,
            "memory": self.mem,
            "data_dir": Path(self.tmp.name),
        }
        load_all_tools(self.registry, self.ctx)

    def tearDown(self):
        self.mem.close()
        self.tmp.cleanup()

    def test_schemas_are_valid(self):
        for schema in self.registry.schemas():
            self.assertIn("name", schema)
            self.assertIn("description", schema)
            self.assertEqual(schema["parameters"].get("type"), "object")
            self.assertIsInstance(schema["parameters"].get("required", []), list)

    def test_calculate(self):
        self.assertIn("96", self.registry.execute("calculate", {"expression": "12 * 8"}))
        self.assertIn("4", self.registry.execute("calculate", {"expression": "sqrt(16)"}))
        self.assertIn("Could not calculate", self.registry.execute("calculate", {"expression": "1/0"}))
        self.assertIn("Could not calculate", self.registry.execute("calculate", {"expression": "__import__('os')"}))

    def test_time_tools(self):
        self.assertIn(":", self.registry.execute("get_time", {}))
        self.assertIn("20", self.registry.execute("get_date", {}))

    def test_notes(self):
        out = self.registry.execute("add_note", {"text": "buy milk"})
        self.assertIn("Note saved", out)
        self.assertIn("buy milk", self.registry.execute("list_notes", {}))
        self.assertIn("buy milk", self.registry.execute("search_notes", {"query": "milk"}))
        self.assertIn("No notes", self.registry.execute("search_notes", {"query": "zzz-nope"}))

    def test_remember_fact_tool(self):
        out = self.registry.execute("remember_fact", {"key": "pet", "fact": "a cat named Mimi"})
        self.assertIn("Remembered", out)
        self.assertEqual(self.mem.get_fact("pet"), "a cat named Mimi")

    def test_files(self):
        (Path(self.tmp.name) / "report.txt").write_text("hello world\n" * 3)
        hits = self.registry.execute("search_files", {"query": "report", "root": self.tmp.name})
        self.assertIn("report.txt", hits)
        self.assertIn("hello world", self.registry.execute("read_file", {"path": str(Path(self.tmp.name) / "report.txt")}))

    def test_unknown_tool(self):
        self.assertIn("no such tool", self.registry.execute("nope_tool", {}))

    def test_plugins_loaded(self):
        self.assertTrue(self.registry.has("say_hello"))
        self.assertTrue(self.registry.has("start_timer"))
        self.assertIn("Hello", self.registry.execute("say_hello", {"name": "Test"}))

    def test_system_info(self):
        out = self.registry.execute("system_info", {})
        self.assertIn("OS:", out)


class BrainOfflineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from core.brain import Brain
        from core.config import Config
        from core.memory import Memory
        from tools.registry import ToolRegistry, load_all_tools

        self.config = Config({})
        self.config._data["paths"]["data_dir"] = self.tmp.name
        self.mem = Memory(Path(self.tmp.name))
        self.registry = ToolRegistry()
        self.ctx = {
            "config": self.config,
            "memory": self.mem,
            "data_dir": Path(self.tmp.name),
        }
        load_all_tools(self.registry, self.ctx)
        self.brain = Brain(self.config, self.mem, self.registry)

    def tearDown(self):
        self.mem.close()
        self.tmp.cleanup()

    def test_offline_calculate(self):
        reply = self.brain.respond("calculate 12 * 8")
        self.assertIn("96", reply)

    def test_offline_time(self):
        reply = self.brain.respond("what time is it")
        self.assertIn(":", reply)

    def test_offline_unknown_is_honest(self):
        reply = self.brain.respond("tell me a story about dragons")
        self.assertIn("offline", reply.lower())

    def test_memory_saved(self):
        self.brain.respond("calculate 2 + 2")
        hist = self.mem.recent_history(5)
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["role"], "user")


class TaskTest(unittest.TestCase):
    def test_task_lifecycle(self):
        import threading
        import time

        tmp = tempfile.TemporaryDirectory()
        from core.tasks import TaskManager

        tm = TaskManager(Path(tmp.name))
        task = tm.create("custom", "do a thing")
        self.assertEqual(task["status"], "queued")

        def runner(t, progress, stop):
            progress("halfway")
            time.sleep(0.05)
            return "done-thing"

        self.assertTrue(tm.start(task["id"], runner))
        for _ in range(50):
            if tm.get(task["id"])["status"] == "done":
                break
            time.sleep(0.05)
        self.assertEqual(tm.get(task["id"])["status"], "done")
        self.assertEqual(tm.get(task["id"])["result"], "done-thing")
        tmp.cleanup()


class GuiImportTest(unittest.TestCase):
    def test_gui_module_imports_or_reports_missing(self):
        from gui.hud import gui_available, run_hud

        if gui_available():
            import gui.hud  # noqa: F401 - import must succeed
        else:
            with self.assertRaises(RuntimeError):
                run_hud(None, None)


if __name__ == "__main__":
    unittest.main()
