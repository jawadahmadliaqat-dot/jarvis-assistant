"""Step 1 tests — routines, proactive alerts, live context.

No network, no API keys, no microphone needed.
Run from the project root: python -m unittest discover -s tests -v
"""

import datetime
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)


def _make_ctx(tmp):
    from core.config import Config
    from core.memory import Memory
    from tools.registry import ToolRegistry, load_all_tools

    config = Config({})
    config._data["paths"]["data_dir"] = tmp
    mem = Memory(Path(tmp))
    registry = ToolRegistry()
    ctx = {"config": config, "memory": mem, "data_dir": Path(tmp)}
    load_all_tools(registry, ctx)
    return config, mem, registry, ctx


class ContextTest(unittest.TestCase):
    def test_part_of_day(self):
        from core.context import part_of_day

        self.assertEqual(part_of_day(2), "late night")
        self.assertEqual(part_of_day(8), "morning")
        self.assertEqual(part_of_day(14), "afternoon")
        self.assertEqual(part_of_day(19), "evening")
        self.assertEqual(part_of_day(23), "night")

    def test_quiet_hours_overnight(self):
        from core.config import Config
        from core.context import in_quiet_hours

        cfg = Config({})
        self.assertTrue(in_quiet_hours(cfg, datetime.datetime(2026, 1, 1, 2, 0)))
        self.assertTrue(in_quiet_hours(cfg, datetime.datetime(2026, 1, 1, 23, 30)))
        self.assertFalse(in_quiet_hours(cfg, datetime.datetime(2026, 1, 1, 12, 0)))
        self.assertFalse(in_quiet_hours(cfg, datetime.datetime(2026, 1, 1, 7, 0, 1)))

    def test_gather_and_render(self):
        from core.context import gather_context, render_context_block

        tmp = tempfile.TemporaryDirectory()
        try:
            config, mem, _reg, _ctx = _make_ctx(tmp.name)
            import time

            mem.add_reminder("call Ali", time.time() + 3600)
            now = datetime.datetime(2026, 11, 24, 2, 15,
                                    tzinfo=datetime.timezone.utc)
            ctx = gather_context(config, mem, now=now)
            self.assertTrue(ctx["late_night"])
            self.assertEqual(ctx["pending_reminders"], 1)
            block = render_context_block(ctx)
            self.assertIn("late night", block)
            self.assertIn("call Ali", block)
            self.assertIn("Pending reminders: 1", block)
            mem.close()
        finally:
            tmp.cleanup()

    def test_active_window_never_crashes(self):
        from core.context import _active_window

        result = _active_window()
        self.assertTrue(result is None or isinstance(result, str))


class RoutineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config, self.mem, self.registry, self.ctx = _make_ctx(self.tmp.name)
        from core.routines import RoutineRunner

        self.runner = RoutineRunner(self.config, self.registry, self.ctx)

    def tearDown(self):
        self.mem.close()
        self.tmp.cleanup()

    def test_defaults_listed(self):
        text = self.runner.list_routines()
        self.assertIn("morning", text)
        self.assertIn("07:00", text)
        self.assertIn("evening", text)

    def test_unknown_routine(self):
        self.assertIn("No routine", self.runner.run("nope"))

    def test_evening_runs_offline(self):
        out = self.runner.run("evening")
        self.assertIn("Good evening", out)
        self.assertIn("No pending reminders", out)

    def test_due_tracking(self):
        now = datetime.datetime(2026, 11, 24, 8, 0)  # after 07:00 morning
        due = [d["name"] for d in self.runner.due_routines(now)]
        self.assertIn("morning", due)
        self.assertNotIn("evening", due)
        self.runner.mark_run("morning", "2026-11-24")
        due = [d["name"] for d in self.runner.due_routines(now)]
        self.assertNotIn("morning", due)
        # Next day it is due again.
        tomorrow = datetime.datetime(2026, 11, 25, 8, 0)
        due = [d["name"] for d in self.runner.due_routines(tomorrow)]
        self.assertIn("morning", due)

    def test_morning_runs_with_mocked_network(self):
        with mock.patch("tools.briefing.get_weather", return_value="Sunny, 20°C"), \
             mock.patch("tools.briefing.search_news", return_value="Headline 1"):
            out = self.runner.run("morning")
        self.assertIn("Good morning", out)
        self.assertIn("Sunny", out)

    def test_routine_tools_registered(self):
        self.assertTrue(self.registry.has("run_routine"))
        self.assertTrue(self.registry.has("list_routines"))
        self.assertIn("morning", self.registry.execute("list_routines", {}))


class ProactiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config, self.mem, self.registry, self.ctx = _make_ctx(self.tmp.name)

    def tearDown(self):
        self.mem.close()
        self.tmp.cleanup()

    def _checker(self):
        from core.proactive import ProactiveChecker

        return ProactiveChecker(self.config, self.mem)

    def test_reminder_fires_once(self):
        import time

        self.mem.add_reminder("call Ali", time.time() - 60)
        checker = self._checker()
        alerts = checker.check(respect_quiet_hours=False)
        self.assertEqual(len(alerts), 1)
        self.assertIn("call Ali", alerts[0])
        # Second check: same reminder must not alert again.
        self.assertEqual(checker.check(respect_quiet_hours=False), [])

    def test_quiet_hours_suppress(self):
        import time

        self.mem.add_reminder("call Ali", time.time() - 60)
        checker = self._checker()
        night = datetime.datetime(2026, 1, 1, 2, 0)
        self.assertEqual(checker.check(now=night, respect_quiet_hours=True), [])
        # Explicit ask still works in quiet hours.
        self.assertEqual(len(checker.check(now=night, respect_quiet_hours=False)), 1)

    def test_disk_alert_and_recovery(self):
        checker = self._checker()
        with mock.patch("core.proactive._disk_free_gb", return_value=1.0):
            alerts = checker.check(respect_quiet_hours=False)
            self.assertEqual(len(alerts), 1)
            self.assertIn("Disk space", alerts[0])
            self.assertEqual(checker.check(respect_quiet_hours=False), [])
        with mock.patch("core.proactive._disk_free_gb", return_value=100.0):
            self.assertEqual(checker.check(respect_quiet_hours=False), [])
        with mock.patch("core.proactive._disk_free_gb", return_value=1.0):
            alerts = checker.check(respect_quiet_hours=False)
            self.assertEqual(len(alerts), 1)  # re-fires after recovery

    def test_finished_task_alert(self):
        from core.proactive import ProactiveChecker
        from core.tasks import TaskManager

        tm = TaskManager(Path(self.tmp.name))
        task = tm.create("custom", "research thing")
        tm._update(task["id"], status="done")
        checker = ProactiveChecker(self.config, self.mem, tasks=tm)
        alerts = checker.check(respect_quiet_hours=False)
        self.assertEqual(len(alerts), 1)
        self.assertIn("research thing", alerts[0])
        self.assertEqual(checker.check(respect_quiet_hours=False), [])

    def test_check_alerts_tool(self):
        self.assertTrue(self.registry.has("check_alerts"))
        out = self.registry.execute("check_alerts", {})
        self.assertIn("Nothing needs", out)


class BrainContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config, self.mem, self.registry, self.ctx = _make_ctx(self.tmp.name)
        from core.brain import Brain

        self.brain = Brain(self.config, self.mem, self.registry)

    def tearDown(self):
        self.mem.close()
        self.tmp.cleanup()

    def test_system_prompt_has_live_context(self):
        prompt = self.brain._system_prompt()
        self.assertIn("Live context", prompt)
        self.assertIn("It is", prompt)
        self.assertIn("Pending reminders: 0", prompt)

    def test_offline_still_works_with_context(self):
        reply = self.brain.respond("calculate 12 * 8")
        self.assertIn("96", reply)


class MemoryMigrationTest(unittest.TestCase):
    def test_done_ts_tracked(self):
        import time

        tmp = tempfile.TemporaryDirectory()
        try:
            from core.memory import Memory

            mem = Memory(Path(tmp.name))
            rid = mem.add_reminder("x", time.time() - 10)
            self.assertEqual(mem.reminders_completed_since(time.time() - 3600), 0)
            mem.mark_reminder_done(rid)
            self.assertEqual(mem.reminders_completed_since(time.time() - 3600), 1)
            mem.add_message("user", "hi")
            self.assertEqual(mem.messages_since(time.time() - 3600), 1)
            mem.close()
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
