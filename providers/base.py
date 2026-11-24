"""Provider interface. Every LLM backend implements these two methods."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class BaseProvider:
    """A chat backend. `messages` use OpenAI-style dicts:
    {"role": "system"|"user"|"assistant"|"tool", "content": str,
     "tool_calls": [...], "tool_call_id": str, "name": str}.
    `tools` is a list of OpenAI-style function schemas.
    """

    name = "base"

    def available(self) -> tuple[bool, str]:
        """(True, '') when this provider can be tried right now."""
        return True, ""

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ProviderResponse:
        raise NotImplementedError
