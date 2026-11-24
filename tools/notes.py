"""Persistent notes — human-readable JSON in the data dir."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from tools.registry import Tool, ToolRegistry


def _notes_path(context: dict[str, Any]) -> Path:
    path = Path(context["data_dir"]) / "notes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load(context: dict[str, Any]) -> list[dict[str, Any]]:
    path = _notes_path(context)
    if not path.exists():
        return []
    try:
        return list(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return []


def _save(context: dict[str, Any], notes: list[dict[str, Any]]) -> None:
    _notes_path(context).write_text(
        json.dumps(notes, indent=2), encoding="utf-8"
    )


def add_note(context: dict[str, Any], text: str) -> str:
    notes = _load(context)
    note = {"id": uuid.uuid4().hex[:8], "text": text.strip(), "created": time.time()}
    notes.append(note)
    _save(context, notes)
    return f"Note saved (#{note['id']}): {text.strip()}"


def list_notes(context: dict[str, Any]) -> str:
    notes = _load(context)
    if not notes:
        return "No notes yet."
    return "\n".join(f"#{n['id']}: {n['text']}" for n in notes)


def search_notes(context: dict[str, Any], query: str) -> str:
    q = query.lower()
    hits = [n for n in _load(context) if q in n["text"].lower()]
    if not hits:
        return f"No notes matching '{query}'."
    return "\n".join(f"#{n['id']}: {n['text']}" for n in hits)


def delete_note(context: dict[str, Any], note_id: str) -> str:
    notes = _load(context)
    kept = [n for n in notes if n["id"] != note_id]
    if len(kept) == len(notes):
        return f"No note with id #{note_id}."
    _save(context, kept)
    return f"Note #{note_id} deleted."


def _remember(context: dict[str, Any], key: str, fact: str) -> str:
    context["memory"].remember_fact(key, fact)
    return f"Remembered: {key} = {fact}"


def register(registry: ToolRegistry, context: dict[str, Any]) -> None:
    registry.register(
        Tool(
            name="remember_fact",
            description="Remember a fact about the user for later (key + value).",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "short key, e.g. birthday"},
                    "fact": {"type": "string", "description": "the fact to remember"},
                },
                "required": ["key", "fact"],
            },
            func=lambda key, fact: _remember(context, key, fact),
        )
    )
    registry.register(
        Tool(
            name="add_note",
            description="Save a note.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            func=lambda text: add_note(context, text),
        )
    )
    registry.register(
        Tool(
            name="list_notes",
            description="List all saved notes.",
            parameters={"type": "object", "properties": {}},
            func=lambda: list_notes(context),
        )
    )
    registry.register(
        Tool(
            name="search_notes",
            description="Search saved notes.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            func=lambda query: search_notes(context, query),
        )
    )
    registry.register(
        Tool(
            name="delete_note",
            description="Delete a note by its id (shown by list_notes).",
            parameters={
                "type": "object",
                "properties": {"note_id": {"type": "string"}},
                "required": ["note_id"],
            },
            func=lambda note_id: delete_note(context, note_id),
        )
    )
