"""Step 2 tests — coding doctor.

No network, no API keys: the LLM is a stub that returns canned JSON
patches. Run from the project root: python -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)


class StubBrain:
    """Pretends to be an LLM: returns a canned reply to ask_llm."""

    def __init__(self, reply_text=None):
        self.reply_text = reply_text

    def ask_llm(self, system, user):
        if self.reply_text is None:
            return None, "offline"
        return self.reply_text, "gemini"


def _patch_json(explanation, edits):
    return json.dumps({"explanation": explanation, "edits": edits})


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.broken = self.dir / "broken.py"
        self.broken.write_text("def foo()\n    return 1\n", encoding="utf-8")
        self.ctx = {"brain": StubBrain()}

    def tearDown(self):
        self.tmp.cleanup()

    def _fix(self, **kwargs):
        from tools.doctor import fix_error

        return fix_error(self.ctx, **kwargs)

    def test_fix_syntax_error(self):
        patch = _patch_json("Missing colon after the function header.", [
            {"file": str(self.broken), "start_line": 1, "end_line": 1,
             "replacement": "def foo():"},
        ])
        self.ctx["brain"] = StubBrain(patch)
        out = self._fix(error="SyntaxError: expected ':'", file=str(self.broken))
        self.assertIn("Missing colon", out)
        self.assertIn("PASS", out)
        self.assertIn("backup", out)
        self.assertTrue((self.dir / "broken.py.bak").exists())
        self.assertEqual(
            (self.dir / "broken.py").read_text(encoding="utf-8"),
            "def foo():\n    return 1\n",
        )
        # The fixed file really compiles.
        r = subprocess.run([sys.executable, "-m", "py_compile", str(self.broken)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)

    def test_traceback_finds_the_file(self):
        patch = _patch_json("Missing colon.", [
            {"file": str(self.broken), "start_line": 1, "end_line": 1,
             "replacement": "def foo():"},
        ])
        self.ctx["brain"] = StubBrain(patch)
        tb = ('Traceback (most recent call last):\n'
              f'  File "{self.broken}", line 1, in <module>\n'
              '    def foo()\nSyntaxError: expected \':\'\n')
        out = self._fix(error=tb)
        self.assertIn("PASS", out)
        self.assertIn("def foo():", self.broken.read_text(encoding="utf-8"))

    def test_offline_refuses_honestly(self):
        self.ctx["brain"] = StubBrain(None)  # offline
        before = self.broken.read_text(encoding="utf-8")
        out = self._fix(error="SyntaxError", file=str(self.broken))
        self.assertIn("offline", out.lower())
        self.assertIn("applied nothing", out.lower())
        self.assertEqual(self.broken.read_text(encoding="utf-8"), before)
        self.assertFalse((self.dir / "broken.py.bak").exists())

    def test_deletion_needs_confirmation(self):
        patch = _patch_json("Remove the bad line.", [
            {"file": str(self.broken), "start_line": 2, "end_line": 2,
             "replacement": ""},
        ])
        self.ctx["brain"] = StubBrain(patch)
        out = self._fix(error="err", file=str(self.broken))
        self.assertIn("did NOT apply", out)
        self.assertEqual(self.broken.read_text(encoding="utf-8"),
                         "def foo()\n    return 1\n")
        out = self._fix(error="err", file=str(self.broken), confirm=True)
        # Deletion applied, but "def foo()" still has a syntax error,
        # so verification honestly reports FAIL.
        self.assertIn("FAIL", out)
        self.assertNotIn("    return 1", self.broken.read_text(encoding="utf-8"))
        self.assertTrue((self.dir / "broken.py.bak").exists())

    def test_large_patch_needs_confirmation(self):
        big = self.dir / "big.py"
        big.write_text("".join(f"x{i} = {i}\n" for i in range(100)),
                       encoding="utf-8")
        patch = _patch_json("Rewrite everything.", [
            {"file": str(big), "start_line": 1, "end_line": 60,
             "replacement": "\n".join(f"y{i} = {i}" for i in range(60))},
        ])
        self.ctx["brain"] = StubBrain(patch)
        out = self._fix(error="err", file=str(big))
        self.assertIn("did NOT apply", out)
        self.assertEqual(len(big.read_text(encoding="utf-8").splitlines()), 100)

    def test_bad_json_returns_suggestion(self):
        self.ctx["brain"] = StubBrain("I think you should add a colon somewhere.")
        before = self.broken.read_text(encoding="utf-8")
        out = self._fix(error="SyntaxError", file=str(self.broken))
        self.assertIn("did not return a usable patch", out)
        self.assertIn("add a colon", out)
        self.assertEqual(self.broken.read_text(encoding="utf-8"), before)

    def test_no_confident_fix_applies_nothing(self):
        self.ctx["brain"] = StubBrain(_patch_json("Cannot tell from this.", []))
        out = self._fix(error="weird", file=str(self.broken))
        self.assertIn("applied nothing", out)

    def test_unsafe_path_refused(self):
        out = self._fix(error="err", file="/etc/passwd")
        self.assertIn("Refusing", out)

    def test_traceback_parsing(self):
        from tools.doctor import _parse_traceback_files

        tb = ('  File "/home/u/a.py", line 12, in f\n'
              '  File "/home/u/b.py", line 3, in g\n')
        self.assertEqual(_parse_traceback_files(tb),
                         [("/home/u/a.py", 12), ("/home/u/b.py", 3)])

    def test_tool_registered(self):
        from core.config import Config
        from core.memory import Memory
        from tools.registry import ToolRegistry, load_all_tools

        config = Config({})
        config._data["paths"]["data_dir"] = self.tmp.name
        mem = Memory(Path(self.tmp.name))
        registry = ToolRegistry()
        ctx = {"config": config, "memory": mem, "data_dir": Path(self.tmp.name)}
        load_all_tools(registry, ctx)
        self.assertTrue(registry.has("fix_error"))
        mem.close()


if __name__ == "__main__":
    unittest.main()
