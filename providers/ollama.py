"""Local Ollama provider — free, runs on your own machine.

Tries the native /api/chat endpoint first (it supports tools), and falls
back to Ollama's OpenAI-compatible /v1/chat/completions endpoint.
No API key needed. CPU-friendly with small models (llama3.2:3b default).
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from providers.base import BaseProvider, ProviderResponse, ToolCall
from providers.openai_compat import (
    OpenAICompatProvider,
    parse_openai_message,
    to_openai_messages,
)


class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self, model: str, base_url: str, timeout: int = 600):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.logger = logging.getLogger("jarvis.providers.ollama")

    def available(self) -> tuple[bool, str]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                return True, ""
            return False, f"Ollama answered HTTP {resp.status_code}"
        except requests.RequestException:
            return False, "Ollama is not reachable (is it running?)"

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ProviderResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(messages),
            "stream": False,
            "options": {"temperature": 0.7},
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": t} for t in tools
            ]
        try:
            resp = requests.post(
                f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
            )
            if resp.status_code == 404:
                return self._chat_via_openai_compat(messages, tools)
            resp.raise_for_status()
        except requests.RequestException:
            raise
        data = resp.json()
        message = data.get("message") or {}
        text = (message.get("content") or "").strip()
        tool_calls: list[ToolCall] = []
        for i, tc in enumerate(message.get("tool_calls") or []):
            fn = tc.get("function") or {}
            args = fn.get("arguments") or {}
            if not isinstance(args, dict):
                args = {}
            tool_calls.append(
                ToolCall(id=f"ollama-{i}", name=fn.get("name", ""), arguments=args)
            )
        return ProviderResponse(text=text, tool_calls=tool_calls)

    def _chat_via_openai_compat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ProviderResponse:
        compat = OpenAICompatProvider(
            model=self.model, api_key="ollama", base_url=f"{self.base_url}/v1",
            timeout=self.timeout,
        )
        return compat.chat(messages, tools)
