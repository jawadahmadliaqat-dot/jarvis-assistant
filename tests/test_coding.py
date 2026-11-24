"""Coding tools tests — write/edit/run/test/git in temp dirs.

No network, no API keys. Run from the project root:
    python -m unittest discover -s tests -v
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PY = f'"{sys.executable}"'


class WriteEditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_creates_and_reads_back(self):
        from tools.coding import write_file

        target = self.dir / "sub" / "hello.txt"
        out = write_file(str(target), "hello jarvis\n")
        self.assertIn("Wrote", out)
        self.assertEqual(target.read_text(encoding="utf-8"), "hello jarvis\n")

    def test_overwrite_creates_backup_with_old_content(self):
        from tools.coding import write_file

        target = self.dir / "note.txt"
        write_file(str(target), "old content")
        out = write_file(str(target), "new content")
        backup = self.dir / "note.txt.jarvis.bak"
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_text(encoding="utf-8"), "old content")
        self.assertEqual(target.read_text(encoding="utf-8"), "new content")
        self.assertIn(".jarvis.bak", out)

    def test_edit_success(self):
        from tools.coding import edit_file, write_file

        target = self.dir / "code.py"
        write_file(str(target), "x = 1\ny = 2\n")
        out = edit_file(str(target), "x = 1", "x = 42")
        self.assertIn("Edited", out)
        self.assertEqual(target.read_text(encoding="utf-8"), "x = 42\ny = 2\n")
        self.assertTrue((self.dir / "code.py.jarvis.bak").exists())

    def test_edit_zero_match_is_error_not_exception(self):
        from tools.coding import edit_file, write_file

        target = self.dir / "code.py"
        write_file(str(target), "x = 1\n")
        out = edit_file(str(target), "missing text", "whatever")
        self.assertIn("Error", out)
        self.assertIn("not found", out)
        self.assertEqual(target.read_text(encoding="utf-8"), "x = 1\n")

    def test_edit_two_matches_is_error(self):
        from tools.coding import edit_file, write_file

        target = self.dir / "code.py"
        write_file(str(target), "x = 1\nx = 1\n")
        out = edit_file(str(target), "x = 1", "x = 9")
        self.assertIn("Error", out)
        self.assertIn("2 times", out)
        self.assertEqual(target.read_text(encoding="utf-8"), "x = 1\nx = 1\n")


class RunCommandTest(unittest.TestCase):
    def test_echo_output_and_exit_zero(self):
        from tools.coding import run_command

        out = run_command(f'{PY} -c "print(12345)"')
        self.assertIn("exit code: 0", out)
        self.assertIn("12345", out)

    def test_failing_command_reports_nonzero_exit(self):
        from tools.coding import run_command

        out = run_command(f'{PY} -c "import sys; sys.exit(3)"')
        self.assertIn("exit code: 3", out)

    def test_timeout_result(self):
        from tools.coding import run_command

        out = run_command(f'{PY} -c "import time; time.sleep(30)"', timeout=1)
        self.assertIn("timed out", out)


class RunTestsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "test_sample.py").write_text(
            "import unittest\n\n\n"
            "class SampleTest(unittest.TestCase):\n"
            "    def test_ok(self):\n"
            "        self.assertEqual(1 + 1, 2)\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_passing_project_reports_passed(self):
        from tools.coding import run_tests

        out = run_tests(str(self.dir))
        self.assertIn("Tests PASSED", out)

    def test_explicit_command_is_used(self):
        from tools.coding import run_tests

        out = run_tests(str(self.dir),
                        command=f'{PY} -m unittest discover -s . -p "test_*.py"')
        self.assertIn("Tests PASSED", out)


@unittest.skipUnless(shutil.which("git"), "git not available")
class GitToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.dir, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"],
                       cwd=self.dir, check=True)
        subprocess.run(["git", "config", "user.name", "Jarvis Test"],
                       cwd=self.dir, check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_commit_diff_flow(self):
        from tools.coding import git_commit, git_diff, git_status

        target = self.dir / "a.txt"
        target.write_text("one\n", encoding="utf-8")
        status = git_status(str(self.dir))
        self.assertIn("a.txt", status)

        out = git_commit("initial commit", str(self.dir))
        self.assertIn("Committed", out)
        hash_part = out.split("Committed ", 1)[1].split(":", 1)[0]
        self.assertEqual(len(hash_part), 40)

        target.write_text("one\ntwo\n", encoding="utf-8")
        diff = git_diff(str(self.dir))
        self.assertIn("+two", diff)

    def test_not_a_repo_is_graceful_error(self):
        from tools.coding import git_status

        plain = Path(tempfile.mkdtemp())
        out = git_status(str(plain))
        self.assertIn("not a git repository", out)


class RegistryTest(unittest.TestCase):
    def test_coding_tools_registered(self):
        import logging

        from tools.registry import ToolRegistry, load_all_tools

        reg = ToolRegistry(logging.getLogger("test.coding"))
        load_all_tools(reg, {"data_dir": tempfile.mkdtemp()})
        for name in ("write_file", "edit_file", "run_command", "run_tests",
                     "git_status", "git_diff", "git_commit"):
            self.assertTrue(reg.has(name), f"missing tool {name}")


if __name__ == "__main__":
    unittest.main()
