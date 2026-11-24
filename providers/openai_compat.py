"""OpenAI-compatible provider (OpenAI, Groq, DeepSeek, OpenRouter,
LM Studio, vLLM, ...). Plain REST — no openai package needed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from providers.base import BaseProvider, ProviderResponse, ToolCall


def to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert internal messages to OpenAI chat format."""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            out.append({"role": "system", "content": m.get("content", "")})
        elif role == "user":
            out.append({"role": "user", "content": m.get("content", "")})
        elif role == "assistant":
            msg: dict[str, Any] = {
                "role": "assistant",
                "content": m.get("content") or None,
            }
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in m["tool_calls"]
                ]
            out.append(msg)
        elif role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id", ""),
                    "content": m.get("content", ""),
                }
            )
    return out


def parse_openai_message(message: dict[str, Any]) -> ProviderResponse:
    text = (message.get("content") or "").strip()
    tool_calls: list[ToolCall] = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (json.JSONDecodeError, TypeError):
            args = {}
        tool_calls.append(
            ToolCall(id=tc.get("id", "call-0"), name=fn.get("name", ""), arguments=args)
        )
    return ProviderResponse(text=text, tool_calls=tool_calls)


class OpenAICompatProvider(BaseProvider):
    name = "openai"

    def __init__(
        self, model: str, api_key: str, base_url: str, timeout: int = 60
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.logger = logging.getLogger("jarvis.providers.openai")

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "no OPENAI_API_KEY set"
        return True, ""

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ProviderResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(messages),
            "temperature": 0.7,
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": t} for t in tools
            ]
            payload["tool_choice"] = "auto"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ProviderResponse(text="The provider returned no answer.")
        return parse_openai_message(choices[0].get("message") or {})
