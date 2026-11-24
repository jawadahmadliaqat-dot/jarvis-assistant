"""Coding doctor — read an error, fix the code, prove it works.

Flow:
  1. Take an error traceback (pasted) and/or a file path. Traceback
     file/line references are parsed automatically.
  2. Read the relevant file(s) (only paths the user may touch: under
     the current working directory, the home directory, or /tmp).
  3. Ask the LLM (Gemini / OpenAI-compatible / Ollama) for a minimal
     JSON patch: {"explanation": "...", "edits": [{"file", "start_line",
     "end_line", "replacement": "..."}]}.
  4. Write a `.bak` backup FIRST, apply the patch, then verify
     (`python -m py_compile` for .py files, or a user-supplied command)
     and report PASS/FAIL.
  5. Risky changes — deleting lines, or a patch touching more than 50
     lines — are NOT applied silently: Jarvis asks for confirmation
     instead (pass confirm=true to apply).

Offline mode cannot do smart fixing: it says so honestly and applies
nothing. The LLM never chooses the verification command and never
runs shell commands by itself.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.registry import Tool, ToolRegistry

MAX_FILE_BYTES = 200_000
MAX_PATCH_LINES = 50
MAX_CONTEXT_LINES = 300

_DOCTOR_SYSTEM = """You are a careful code-fixing assistant. Fix ONLY the
error described. Keep the patch minimal: change as few lines as possible,
do not rewrite unrelated code, do not rename things, do not add features.

Reply with JSON ONLY, no other text, no markdown fences:
{"explanation": "<1-2 lines, plain language>",
 "edits": [{"file": "<path as given>", "start_line": <int, 1-based>,
            "end_line": <int, 1-based, inclusive>,
            "replacement": "<new lines, without trailing newline>"}]}

If you cannot fix it confidently, reply:
{"explanation": "<why not, and what to try>", "edits": []}
"""


def _safe_path(path_str: str) -> Path | None:
    """Resolve a user-supplied path; refuse system/sensitive locations."""
    try:
        path = Path(path_str).expanduser().resolve()
    except Exception:
        return None
    blocked = (
        Path("/etc"), Path("/usr"), Path("/bin"), Path("/sbin"),
        Path("/proc"), Path("/sys"), Path("/boot"),
    )
    if any(path == b or b in path.parents for b in blocked):
        return None
    if "site-packages" in path.parts or "dist-packages" in path.parts:
        return None
    allowed_roots = [Path.cwd(), Path.home(), Path("/tmp")]
    if not any(path == r or r in path.parents for r in allowed_roots):
        return None
    return path


def _parse_traceback_files(error: str) -> list[tuple[str, int]]:
    """Extract (file, line) pairs from a Python traceback."""
    found: list[tuple[str, int]] = []
    for m in re.finditer(r'File "([^"]+)", line (\d+)', error or ""):
        found.append((m.group(1), int(m.group(2))))
    return found


def _read_snippet(path: Path, focus_line: int | None = None) -> str:
    """File contents with line numbers; windowed around the error line."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) <= MAX_CONTEXT_LINES or focus_line is None:
        window = list(enumerate(lines, start=1))
    else:
        lo = max(1, focus_line - 60)
        hi = min(len(lines), focus_line + 60)
        window = list(enumerate(lines, start=1))[lo - 1:hi]
    numbered = "\n".join(f"{n:4d}| {line}" for n, line in window)
    return numbered


def _extract_json(text: str) -> dict | None:
    """Parse the LLM reply: plain JSON, fenced JSON, or first {...} block."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(cleaned[start:end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _backup_path(path: Path) -> Path:
    """First free .bak name — never overwrites an existing backup."""
    candidate = path.with_name(path.name + ".bak")
    if not candidate.exists():
        return candidate
    i = 1
    while True:
        candidate = path.with_name(f"{path.name}.bak.{i}")
        if not candidate.exists():
            return candidate
        i += 1


def _apply_edits(path: Path, edits: list[dict]) -> tuple[int, int]:
    """Apply line-range edits bottom-up. Returns (lines added, lines removed)."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    added = removed = 0
    for edit in sorted(edits, key=lambda e: e["start_line"], reverse=True):
        start = int(edit["start_line"])
        end = int(edit["end_line"])
        if start < 1 or end < start or end > len(lines):
            raise ValueError(
                f"edit range {start}-{end} is outside {path.name} "
                f"({len(lines)} lines)"
            )
        replacement = str(edit.get("replacement", "")).splitlines()
        removed += end - start + 1
        added += len(replacement)
        lines[start - 1:end] = replacement
    text = "\n".join(lines)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")
    return added, removed


def _verify(path: Path, verify_command: str | None) -> tuple[bool, str]:
    """Run the verification command. Returns (passed, output snippet)."""
    if verify_command:
        cmd = verify_command
    elif path.suffix == ".py":
        cmd = f'"{sys.executable}" -m py_compile "{path}"'
    else:
        return True, "No verifier for this file type — skipped."
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"Verification could not run: {exc}"
    output = (result.stdout + result.stderr).strip()
    if result.returncode == 0:
        return True, "Verification passed."
    return False, f"Verification FAILED:\n{output[:1000]}"


def fix_error(context: dict[str, Any], error: str = "", file: str = "",
              verify_command: str | None = None,
              confirm: bool = False) -> str:
    """Diagnose an error and (with a backup) fix the code, then verify."""
    error = (error or "").strip()
    candidates: list[tuple[Path, int | None]] = []
    if file:
        resolved = _safe_path(file)
        if resolved is None:
            return f"Refusing to touch '{file}': outside allowed locations."
        if not resolved.is_file():
            return f"File not found: {file}"
        candidates.append((resolved, None))
    for path_str, line_no in _parse_traceback_files(error):
        resolved = _safe_path(path_str)
        if resolved is not None and resolved.is_file():
            if resolved not in [c[0] for c in candidates]:
                candidates.append((resolved, line_no))
    if not candidates and not error:
        return (
            "Give me an error traceback and/or a file path, e.g. "
            "'fix the error in main.py' or paste the traceback."
        )

    brain = context.get("brain")
    if brain is None or not hasattr(brain, "ask_llm"):
        return (
            "The coding doctor needs the LLM brain, which is not loaded "
            "in this session. Run it from the Jarvis CLI or GUI."
        )

    # Gather file context for the LLM.
    parts: list[str] = []
    for path, focus in candidates:
        if path.stat().st_size > MAX_FILE_BYTES:
            return f"File too large to fix safely: {path}"
        parts.append(
            f"=== {path} ===\n{_read_snippet(path, focus)}"
        )
    user_msg = (
        f"Error:\n{error or '(no error text given — find the problem in the file)'}"
        f"\n\nFiles:\n" + "\n\n".join(parts)
    )
    text, provider = brain.ask_llm(_DOCTOR_SYSTEM, user_msg)
    if text is None:
        return (
            "Smart fixing needs an LLM (a Gemini API key or local Ollama), "
            "and I'm offline right now — no provider answered. Add a "
            "GEMINI_API_KEY to .env or start Ollama, then ask again. "
            "I applied nothing."
        )
    parsed = _extract_json(text)
    if parsed is None:
        return (
            "The model did not return a usable patch, so I applied "
            f"nothing. Its suggestion:\n{text[:2000]}"
        )
    explanation = str(parsed.get("explanation", "")).strip()
    edits = parsed.get("edits") or []
    if not isinstance(edits, list):
        edits = []
    if not edits:
        return (
            f"{explanation or 'No confident fix found.'}\n"
            "I applied nothing — paste more of the traceback or the "
            "surrounding code and I will try again."
        )

    # Validate + classify the patch before touching anything.
    by_file: dict[Path, list[dict]] = {}
    total_lines = 0
    deletes_lines = False
    for edit in edits:
        try:
            start, end = int(edit["start_line"]), int(edit["end_line"])
            replacement = str(edit.get("replacement", ""))
        except (KeyError, TypeError, ValueError):
            return "The model's patch was malformed — I applied nothing."
        path = _safe_path(str(edit.get("file", "")))
        if path is None or not path.is_file():
            return (
                f"The model tried to edit '{edit.get('file')}', which is "
                "not an allowed/existing file — I applied nothing."
            )
        total_lines += (end - start + 1) + len(replacement.splitlines())
        if not replacement.strip():
            deletes_lines = True
        by_file.setdefault(path, []).append(
            {"start_line": start, "end_line": end, "replacement": replacement}
        )
    risky = deletes_lines or total_lines > MAX_PATCH_LINES
    if risky and not confirm:
        reason = (
            "it deletes code" if deletes_lines
            else f"it touches {total_lines} lines (limit {MAX_PATCH_LINES})"
        )
        return (
            f"Proposed fix ({explanation or 'no explanation given'}), but "
            f"{reason} — so I did NOT apply it. Say 'yes, apply it' to "
            "confirm, and I will back the file up first."
        )

    # Backup first, then apply, then verify.
    results: list[str] = []
    for path, file_edits in by_file.items():
        backup = _backup_path(path)
        backup.write_bytes(path.read_bytes())
        try:
            added, removed = _apply_edits(path, file_edits)
        except ValueError as exc:
            return f"Patch failed validation: {exc} — backup kept at {backup}."
        passed, verify_out = _verify(
            path, verify_command if len(by_file) == 1 else None
        )
        status = "PASS" if passed else "FAIL"
        results.append(
            f"{path.name}: -{removed}/+{added} lines, backup {backup.name}, "
            f"verification {status}.\n{verify_out}"
        )
    summary = explanation or "Fix applied."
    return f"{summary}\n\n" + "\n".join(results)


def register(registry: ToolRegistry, context: dict[str, Any]) -> None:
    registry.register(
        Tool(
            name="fix_error",
            description=(
                "Fix a code error: give a traceback and/or file path. "
                "Backs the file up (.bak), applies a minimal patch, "
                "verifies it. Needs an LLM (not offline). Deletions and "
                "large patches need confirm=true."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                    "file": {"type": "string"},
                    "verify_command": {"type": "string"},
                    "confirm": {"type": "boolean"},
                },
                "required": [],
            },
            func=lambda error="", file="", verify_command=None, confirm=False: fix_error(
                context, error, file, verify_command, confirm
            ),
        )
    )
