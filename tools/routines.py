"""Routine tools — run/list the named routines from config.

Routines are defined in config.yaml under `routines.definitions`
(see core/routines.py). Running one executes its actions (tool calls
and/or spoken lines) and records it as run for today.
"""

from __future__ import annotations

from typing import Any

from core.routines import RoutineRunner
from tools.registry import Tool, ToolRegistry


def _runner(registry: ToolRegistry, context: dict[str, Any]) -> RoutineRunner:
    return RoutineRunner(context["config"], registry, context)


def register(registry: ToolRegistry, context: dict[str, Any]) -> None:
    registry.register(
        Tool(
            name="run_routine",
            description="Run a named routine (e.g. 'morning' or 'evening').",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            func=lambda name: _runner(registry, context).run(name),
        )
    )
    registry.register(
        Tool(
            name="list_routines",
            description="List the configured routines and their times.",
            parameters={"type": "object", "properties": {}},
            func=lambda: _runner(registry, context).list_routines(),
        )
    )
