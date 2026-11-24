"""Google Gemini provider (REST, no SDK needed).

Uses the v1beta generateContent endpoint with functionDeclarations so
Gemini can call Jarvis tools natively. Key from GEMINI_API_KEY
(env or .env). Free tier is enough for daily use.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from providers.base import BaseProvider, ProviderResponse, ToolCall

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"


def _to_gemini_messages(messages: list[dict[str, Any]]) -> tuple[dict | None, list[dict]]:
    system = None
    contents: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            system = {"parts": [{"text": m.get("content", "")}]}
        elif role == "user":
            contents.append({"role": "user", "parts": [{"text": m.get("content", "")}]})
        elif role == "assistant":
            parts: list[dict] = []
            if m.get("content"):
                parts.append({"text": m["content"]})
            for tc in m.get("tool_calls") or []:
                parts.append(
                    {"functionCall": {"name": tc["name"], "args": tc["arguments"]}}
                )
            if parts:
                contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            contents.append(
                {
                    "role": "function",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": m.get("name", "tool"),
                                "response": {"result": m.get("content", "")},
                            }
                        }
                    ],
                }
            )
    return system, contents


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, model: str, api_key: str, timeout: int = 60):
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.logger = logging.getLogger("jarvis.providers.gemini")

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "no GEMINI_API_KEY set"
        return True, ""

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ProviderResponse:
        system, contents = _to_gemini_messages(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": 0.7},
        }
        if system:
            payload["systemInstruction"] = system
        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t["name"],
                            "description": t.get("description", ""),
                            "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                        }
                        for t in tools
                    ]
                }
            ]
        url = f"{API_ROOT}/{self.model}:generateContent"
        resp = requests.post(
            url, params={"key": self.api_key}, json=payload, timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return ProviderResponse(
                text="Gemini returned no answer (possibly blocked). "
                "Try rephrasing, sir."
            )
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for i, part in enumerate(parts):
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                args = fc.get("args") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append(
                    ToolCall(id=f"gemini-{i}", name=fc.get("name", ""), arguments=args)
                )
        return ProviderResponse(text="".join(text_parts).strip(), tool_calls=tool_calls)
