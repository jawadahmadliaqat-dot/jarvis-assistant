"""Step 3 tests — talking cartoon avatar (pure math + Qt widget when available).

Run from the project root: python -m unittest discover -s tests -v
"""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class AvatarMathTest(unittest.TestCase):
    def test_mouth_openness_bounds(self):
        from gui.hud import avatar_mouth_openness

        for level in (0.0, 0.3, 0.7, 1.0):
            for t in (0.0, 0.3, 1.0, 2.5):
                v = avatar_mouth_openness(level, t)
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 1.0)

    def test_mouth_scales_with_level(self):
        from gui.hud import avatar_mouth_openness

        self.assertEqual(avatar_mouth_openness(0.0, 1.0), 0.0)
        # At t where sin is near 1 the mouth is wide open at full level.
        import math

        t_peak = (math.pi / 2) / 7.0
        self.assertAlmostEqual(avatar_mouth_openness(1.0, t_peak), 1.0, places=2)
        self.assertLess(avatar_mouth_openness(0.2, t_peak),
                        avatar_mouth_openness(1.0, t_peak))

    def test_states_known(self):
        from gui.hud import AVATAR_STATES

        self.assertEqual(set(AVATAR_STATES),
                         {"idle", "listening", "thinking", "speaking"})


@unittest.skipUnless(
    __import__("importlib").util.find_spec("PyQt6") is not None,
    "PyQt6 not installed — avatar widget rendering cannot be tested here",
)
class AvatarWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_widget_states_and_paint(self):
        from gui.hud import AvatarWidget

        w = AvatarWidget()
        w.resize(220, 200)
        for state in ("idle", "listening", "thinking", "speaking"):
            w.set_state(state)
            w.set_level(0.8)
            w.show()
            self.app.processEvents()
            pixmap = w.grab()  # forces paintEvent
            self.assertFalse(pixmap.isNull())
        w.set_state("nonsense")
        self.assertEqual(w.state, "idle")
        w.close()

    def test_hud_builds_with_avatar(self):
        from unittest import mock

        from gui.hud import JarvisHUD

        brain = mock.MagicMock()
        brain.active_provider_name = "offline"
        brain.task_manager = mock.MagicMock()
        brain.task_manager.list_tasks.return_value = []
        config = mock.MagicMock()
        config.assistant_name = "Jarvis"
        config.get.side_effect = lambda *a, **k: k.get("default", 1000)
        hud = JarvisHUD(brain, config, tts=None)
        self.assertIsNotNone(hud.avatar)
        hud.set_state("speaking")
        self.assertEqual(hud.avatar.state, "speaking")
        hud.close()


if __name__ == "__main__":
    unittest.main()
