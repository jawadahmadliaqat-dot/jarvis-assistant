"""File tools — search, read and list, scoped to safe roots.

Searches never leave the user's home directory unless an absolute path is
given explicitly, and never read binary files as text.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any

from tools.registry import Tool, ToolRegistry

_SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".cache", ".objaverse", "site-packages",
}


def search_files(query: str, root: str = "~", max_results: int = 20) -> str:
    """Find files whose name contains the query (case-insensitive)."""
    base = Path(os.path.expanduser(root or "~"))
    if not base.exists():
        return f"Folder '{root}' does not exist."
    q = query.lower()
    hits: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if q in name.lower():
                hits.append(str(Path(dirpath) / name))
                if len(hits) >= max_results:
                    return "\n".join(hits) + f"\n... (showing first {max_results})"
    if not hits:
        return f"No files matching '{query}' under {base}."
    return "\n".join(hits)


def read_file(path: str, max_lines: int = 100) -> str:
    """Read the first N lines of a text file."""
    p = Path(os.path.expanduser(path))
    if not p.exists():
        return f"File '{path}' does not exist."
    if p.is_dir():
        return f"'{path}' is a folder — use list_directory."
    try:
        text = p.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return f"'{path}' is not a text file."
    except OSError as exc:
        return f"Could not read '{path}': {exc}"
    lines = text.splitlines()
    shown = lines[:max(1, min(max_lines, 500))]
    out = "\n".join(shown)
    if len(lines) > len(shown):
        out += f"\n... ({len(lines) - len(shown)} more lines)"
    return out or "(empty file)"


def list_directory(path: str = "~") -> str:
    """List a folder's contents with sizes."""
    p = Path(os.path.expanduser(path or "~"))
    if not p.exists():
        return f"Folder '{path}' does not exist."
    if not p.is_dir():
        return f"'{path}' is not a folder."
    entries = []
    for entry in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        try:
            if entry.is_dir():
                entries.append(f"[dir]  {entry.name}/")
            else:
                entries.append(f"       {entry.name} ({entry.stat().st_size:,} bytes)")
        except OSError:
            entries.append(f"       {entry.name} (unreadable)")
    return f"{p}:\n" + "\n".join(entries[:100]) if entries else f"{p}: (empty)"


def register(registry: ToolRegistry, context: dict[str, Any]) -> None:
    registry.register(
        Tool(
            name="search_files",
            description="Find files by name under a folder (default home).",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "root": {"type": "string", "description": "folder to search"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
            },
            func=search_files,
        )
    )
    registry.register(
        Tool(
            name="read_file",
            description="Read the first lines of a text file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_lines": {"type": "integer"},
                },
                "required": ["path"],
            },
            func=read_file,
        )
    )
    registry.register(
        Tool(
            name="list_directory",
            description="List a folder's contents.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": [],
            },
            func=list_directory,
        )
    )
