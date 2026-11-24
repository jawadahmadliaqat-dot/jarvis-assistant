"""Coding tools — write/edit files, run commands and tests, drive git.

Built for the coding-agent loop: plan -> write -> run -> read the error
-> fix -> prove it with tests. Safety culture matches tools/doctor.py:

  * write_file / edit_file ALWAYS back the previous version up first
    (`<path>.jarvis.bak`, then `.jarvis.bak.1`, ... — never overwritten).
  * run_command is a sensitive tool (see ambient/manifest.json): the
    trust gate requires confirm=true before it executes at all.
  * Every failure is a plain result string, never an exception — the
    tool loop must not crash because a command failed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.registry import Tool, ToolRegistry

MAX_OUTPUT_CHARS = 8000
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 300


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _backup(path: Path) -> Path:
    """Copy path to the first free `<path>.jarvis.bak` name."""
    candidate = path.with_name(path.name + ".jarvis.bak")
    if not candidate.exists():
        shutil.copy2(path, candidate)
        return candidate
    i = 1
    while True:
        candidate = path.with_name(f"{path.name}.jarvis.bak.{i}")
        if not candidate.exists():
            shutil.copy2(path, candidate)
            return candidate
        i += 1


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated, {len(text) - limit} more chars)"


def _run(command: str, cwd: str | None = None,
         timeout: int = DEFAULT_TIMEOUT) -> tuple[int | None, str, str, bool]:
    """Run a shell command. Returns (exit_code, stdout, stderr, timed_out)."""
    timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    workdir = os.path.expanduser(cwd) if cwd else None
    if workdir and not Path(workdir).is_dir():
        return None, "", f"Working folder '{cwd}' does not exist.", False
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=workdir,
        )
    except subprocess.TimeoutExpired:
        return None, "", "", True
    except Exception as exc:  # noqa: BLE001 - a failed launch is data
        return None, "", f"Could not run command: {exc}", False
    return result.returncode, result.stdout, result.stderr, False


def _format_run(command: str, code: int | None, out: str, err: str,
                timed_out: bool, timeout: int) -> str:
    if timed_out:
        return (f"Command timed out after {timeout}s and was killed: "
                f"{command}")
    if code is None:
        return f"Error: {err.strip()}" if err.strip() else "Error: command did not run."
    parts = [f"exit code: {code}", f"$ {command}"]
    if out.strip():
        parts.append("--- stdout ---\n" + _truncate(out.strip()))
    if err.strip():
        parts.append("--- stderr ---\n" + _truncate(err.strip()))
    if not out.strip() and not err.strip():
        parts.append("(no output)")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# File writing / editing
# ---------------------------------------------------------------------------

def write_file(path: str, content: str) -> str:
    """Create or overwrite a text file (backing up any existing version)."""
    p = Path(os.path.expanduser(path))
    try:
        backup_note = ""
        if p.exists():
            if p.is_dir():
                return f"'{path}' is a folder — cannot overwrite it with a file."
            backup = _backup(p)
            backup_note = f" Previous version backed up to {backup.name}."
        p.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        p.write_bytes(data)
    except OSError as exc:
        return f"Error: could not write '{path}': {exc}"
    return f"Wrote {len(data):,} bytes to {p}.{backup_note}"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace the single exact occurrence of old_text in a file."""
    p = Path(os.path.expanduser(path))
    if not p.exists():
        return f"Error: file '{path}' does not exist."
    if p.is_dir():
        return f"Error: '{path}' is a folder, not a file."
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: '{path}' is not a text file."
    except OSError as exc:
        return f"Error: could not read '{path}': {exc}"
    count = text.count(old_text)
    if count == 0:
        return f"Error: old_text not found in '{path}' — no edit made."
    if count > 1:
        return (f"Error: old_text occurs {count} times in '{path}' — "
                "include more surrounding text so exactly one match remains. "
                "No edit made.")
    try:
        backup = _backup(p)
        p.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
    except OSError as exc:
        return f"Error: could not edit '{path}': {exc}"
    return f"Edited {p} (backup: {backup.name})."


# ---------------------------------------------------------------------------
# Commands and tests
# ---------------------------------------------------------------------------

def run_command(command: str, cwd: str = "", timeout: int = DEFAULT_TIMEOUT,
                confirm: bool = False) -> str:
    """Run a shell command and return its exit code and output.

    Sensitive tool: the trust gate requires confirm=true (see
    ambient/manifest.json) — `confirm` is accepted here so the argument
    is part of the call, but enforcement lives in the gate, mirroring
    how lock_screen / fix_error are wired.
    """
    code, out, err, timed_out = _run(command, cwd or None, timeout)
    return _format_run(command, code, out, err, timed_out, timeout)


def _detect_test_command(base: Path) -> str:
    """Pick a test command for the project at `base`."""
    has_pytest_traces = (
        (base / "pytest.ini").exists()
        or (base / "pyproject.toml").exists()
        or (base / "setup.cfg").exists()
        or (base / "tox.ini").exists()
        or any(base.rglob("test_*.py"))
        or any(base.rglob("*_test.py"))
    )
    if has_pytest_traces:
        try:
            import pytest  # noqa: F401
            return f'"{sys.executable}" -m pytest -q'
        except ImportError:
            pass
    return f'"{sys.executable}" -m unittest discover -s . -p "test_*.py"'


def run_tests(path: str = "", command: str = "") -> str:
    """Run a project's tests (given command, or auto-detected)."""
    base = Path(os.path.expanduser(path)) if path else Path.cwd()
    if not base.is_dir():
        return f"Error: '{path}' is not a folder."
    cmd = command.strip() if command else _detect_test_command(base)
    code, out, err, timed_out = _run(cmd, str(base), DEFAULT_TIMEOUT * 2)
    if timed_out:
        return f"Tests timed out: {cmd}"
    if code is None:
        return f"Error: tests did not run: {err.strip()}"
    combined = (out + err).strip()
    tail = "\n".join(combined.splitlines()[-25:]) if combined else "(no output)"
    verdict = "PASSED" if code == 0 else f"FAILED (exit code {code})"
    return f"Tests {verdict} — $ {cmd}\n--- output (tail) ---\n{_truncate(tail)}"


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

def _git(path: str, *git_args: str) -> tuple[int | None, str, str, bool]:
    base = Path(os.path.expanduser(path)) if path else Path.cwd()
    cmd = f'git -C "{base}" ' + " ".join(
        f'"{a}"' if any(c in a for c in " \t") else a for a in git_args
    )
    return _run(cmd, None, DEFAULT_TIMEOUT)


def _not_a_repo(text: str) -> bool:
    return "not a git repository" in text.lower()


def git_status(path: str = "") -> str:
    """Show short git status for a repo."""
    code, out, err, _ = _git(path, "status", "--short", "--branch")
    if code is None:
        return f"Error: git status did not run: {err.strip()}"
    if _not_a_repo(err):
        return f"Error: '{path or '.'}' is not a git repository."
    if code != 0:
        return f"Error: git status failed: {(err or out).strip()}"
    return out.strip() or "Clean working tree."


def git_diff(path: str = "") -> str:
    """Show the unstaged git diff for a repo."""
    code, out, err, _ = _git(path, "diff")
    if code is None:
        return f"Error: git diff did not run: {err.strip()}"
    if _not_a_repo(err):
        return f"Error: '{path or '.'}' is not a git repository."
    if code != 0:
        return f"Error: git diff failed: {(err or out).strip()}"
    return _truncate(out.strip()) if out.strip() else "No unstaged changes."


def git_commit(message: str, path: str = "") -> str:
    """Stage everything and commit; returns the new commit hash."""
    code, out, err, _ = _git(path, "add", "-A")
    if code is None:
        return f"Error: git add did not run: {err.strip()}"
    if _not_a_repo(err):
        return f"Error: '{path or '.'}' is not a git repository."
    if code != 0:
        return f"Error: git add failed: {(err or out).strip()}"
    code, out, err, _ = _git(path, "commit", "-m", message)
    if code != 0:
        detail = (out + err).strip()
        if "nothing to commit" in detail.lower():
            return "Nothing to commit — working tree is clean."
        return f"Error: git commit failed: {detail}"
    code, out, err, _ = _git(path, "rev-parse", "HEAD")
    commit_hash = out.strip() if code == 0 else "(unknown)"
    return f"Committed {commit_hash}: {message}"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(registry: ToolRegistry, context: dict[str, Any]) -> None:
    registry.register(
        Tool(
            name="write_file",
            description=(
                "Create or overwrite a text file (parent folders are "
                "created; an existing file is backed up to "
                "<path>.jarvis.bak first)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            func=write_file,
        )
    )
    registry.register(
        Tool(
            name="edit_file",
            description=(
                "Replace one exact piece of text in a file. old_text must "
                "occur exactly once; the file is backed up first."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            },
            func=edit_file,
        )
    )
    registry.register(
        Tool(
            name="run_command",
            description=(
                "Run a shell command and return its exit code and output. "
                "SENSITIVE: requires confirm=true (the user confirmed in "
                "this conversation)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string", "description": "working folder"},
                    "timeout": {"type": "integer",
                                "description": "seconds, max 300"},
                    "confirm": {"type": "boolean"},
                },
                "required": ["command"],
            },
            func=run_command,
        )
    )
    registry.register(
        Tool(
            name="run_tests",
            description=(
                "Run a project's tests: the given command, or auto-detect "
                "(pytest when present, else unittest discover)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "project folder"},
                    "command": {"type": "string"},
                },
                "required": [],
            },
            func=run_tests,
        )
    )
    registry.register(
        Tool(
            name="git_status",
            description="Show git status (short) for a repository.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": [],
            },
            func=git_status,
        )
    )
    registry.register(
        Tool(
            name="git_diff",
            description="Show the unstaged git diff for a repository.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": [],
            },
            func=git_diff,
        )
    )
    registry.register(
        Tool(
            name="git_commit",
            description="Stage all changes in a repository and commit them.",
            parameters={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["message"],
            },
            func=git_commit,
        )
    )
