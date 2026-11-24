"""Example plugin: a friendly greeting tool.

Drop-in plugins need only a TOOLS list (or a register(registry, context)
function). Jarvis picks the tool up on next launch — no core changes.
"""

from tools.registry import Tool

TOOLS = [
    Tool(
        name="say_hello",
        description="Greet someone warmly by name.",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        func=lambda name: f"Hello, {name}! Good to see you, sir.",
    )
]
