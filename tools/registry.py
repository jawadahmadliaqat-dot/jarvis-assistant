"""Tool registry: tools are plain functions + OpenAI-style JSON schemas.

The LLM can only call registered tools. Execution validates required
arguments, catches exceptions, and returns a plain string — the loop never
crashes because a tool failed.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    func: Callable[..., str] | None = None

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    def __init__(self, logger: logging.Logger | None = None):
        self._tools: dict[str, Tool] = {}
        self.logger = logger or logging.getLogger("jarvis.tools")
        self.context: dict[str, Any] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            self.logger.warning("tool %s already registered; overwriting", tool.name)
        self._tools[tool.name] = tool

    def all_tools(self) -> list[Tool]:
        return [self._tools[k] for k in sorted(self._tools)]

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self.all_tools()]

    def has(self, name: str) -> bool:
        return name in self._tools

    def execute(self, name: str, arguments: dict[str, Any] | None) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: no such tool '{name}'."
        if tool.func is None:
            return f"Error: tool '{name}' has no implementation."
        args = dict(arguments or {})
        required = (tool.parameters.get("required") or [])
        missing = [r for r in required if r not in args or args[r] in (None, "")]
        if missing:
            return f"Error: tool '{name}' is missing required arguments: {missing}."
        try:
            result = tool.func(**args)
        except Exception as exc:  # noqa: BLE001 - tool failure is data
            self.logger.exception("tool %s failed", name)
            return f"Error running {name}: {exc}"
        if result is None:
            return f"{name} finished."
        return str(result)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_BUILTIN_TOOL_MODULES = [
    "search",
    "weather",
    "system",
    "files",
    "notes",
    "reminders",
    "timecalc",
    "briefing",
    "research",
]


def load_all_tools(registry: ToolRegistry, context: dict[str, Any]) -> None:
    """Import built-in tool modules (they self-register) and load plugins."""
    registry.context = context
    for mod_name in _BUILTIN_TOOL_MODULES:
        try:
            module = importlib.import_module(f"tools.{mod_name}")
        except Exception as exc:  # noqa: BLE001
            registry.logger.warning("could not load tool module %s: %s", mod_name, exc)
            continue
        _register_module(registry, module, context)
    load_plugins(registry, context)


def _register_module(registry: ToolRegistry, module, context: dict[str, Any]) -> None:
    if hasattr(module, "register"):
        module.register(registry, context)
    elif hasattr(module, "TOOLS"):
        for tool in module.TOOLS:
            registry.register(tool)


def load_plugins(registry: ToolRegistry, context: dict[str, Any]) -> None:
    """Drop-in plugins: any .py file in plugins/ (or <data_dir>/plugins)."""
    roots: list[Path] = [Path(__file__).resolve().parent.parent / "plugins"]
    data_plugins = context.get("data_dir")
    if data_plugins:
        roots.append(Path(data_plugins) / "plugins")
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"jarvis_plugin_{path.stem}", path
                )
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                _register_module(registry, module, context)
                registry.logger.info("loaded plugin %s", path.name)
            except Exception as exc:  # noqa: BLE001 - a bad plugin must not kill Jarvis
                registry.logger.warning("could not load plugin %s: %s", path.name, exc)
