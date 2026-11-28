"""Offline provider — no LLM, no network model, no key.

Routes the user's text to local tools by keyword, so Jarvis stays useful
when every other provider is unavailable. It is honest about being offline:
its replies say so, and it never invents an answer it cannot verify.
"""

from __future__ import annotations

import re
from typing import Any

from providers.base import BaseProvider, ProviderResponse, ToolCall

_INTENT_PATTERNS: list[tuple[str, str, dict[str, Any]]] = [
    # (regex, tool name, fixed arguments)
    (r"\b(what('| i)s the time|time is it|current time)\b", "get_time", {}),
    (r"\b(today'?s date|what('| i)s the date|current date)\b", "get_date", {}),
    (r"\bmorning briefing\b|\bbrief(ing)? me\b", "morning_briefing", {}),
    (r"\b(weather|temperature|forecast)\b", "get_weather", {}),
    (r"\b(news|headlines)\b", "search_news", {}),
    (r"\b(open|launch|start)\b", "open_app", {}),
    (r"\b(remember|note that|save this)\b", "remember_fact", {}),
    (r"\b(my notes|show notes|list notes)\b", "list_notes", {}),
    (r"\b(remind me|set a reminder)\b", "add_reminder", {}),
    (r"\b(my reminders|list reminders)\b", "list_reminders", {}),
    (r"\b(check alerts|anything (i should|to) know|anything needing attention)\b", "check_alerts", {}),
    (r"\b(system|CPU|RAM|disk|battery)\b.*\b(usage|info|status)\b", "system_info", {}),
    (r"\bsearch (the web )?for\b|\bgoogle\b|\blook up\b", "web_search", {}),
]


class OfflineProvider(BaseProvider):
    name = "offline"

    def __init__(self, config, registry):
        self.config = config
        self.registry = registry

    def available(self) -> tuple[bool, str]:
        return True, ""

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ProviderResponse:
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = m.get("content", "")
                break
        text = user_text.lower()

        # Calculator: "calculate 12 * 8" or bare arithmetic.
        calc = re.search(r"(?:calculate|calc|compute)\s+(.+)", user_text, re.IGNORECASE)
        if calc:
            return ProviderResponse(
                tool_calls=[
                    ToolCall(id="off-0", name="calculate", arguments={"expression": calc.group(1)})
                ]
            )
        if re.fullmatch(r"[\d\s+\-*/().%^]+", text.strip()) and re.search(r"\d", text):
            return ProviderResponse(
                tool_calls=[
                    ToolCall(id="off-0", name="calculate", arguments={"expression": text.strip()})
                ]
            )

        for pattern, tool_name, args in _INTENT_PATTERNS:
            if re.search(pattern, text):
                arguments = dict(args)
                if tool_name == "get_weather":
                    city = re.search(r"weather (?:in|for|at)\s+([a-zA-Z\s]+)", user_text, re.IGNORECASE)
                    if city:
                        arguments["city"] = city.group(1).strip().title()
                elif tool_name == "web_search":
                    q = re.sub(r"^(search (the web )?for|google|look up)\s+", "", user_text, flags=re.IGNORECASE).strip()
                    arguments["query"] = q or user_text
                elif tool_name == "open_app":
                    app = re.sub(r"^(open|launch|start)\s+", "", user_text, flags=re.IGNORECASE).strip()
                    arguments["app"] = app
                elif tool_name == "remember_fact":
                    fact = re.sub(r"^(remember|note that|save this)\s+(that\s+)?", "", user_text, flags=re.IGNORECASE).strip()
                    m = re.match(r"my\s+(.+?)\s+is\s+(.+)$", fact, re.IGNORECASE)
                    if m:
                        arguments["key"] = m.group(1).strip()
                        arguments["fact"] = m.group(2).strip()
                    else:
                        arguments["key"] = "note"
                        arguments["fact"] = fact
                elif tool_name == "add_reminder":
                    body = re.sub(r"^remind me to\s+", "", user_text, flags=re.IGNORECASE).strip()
                    m = re.match(
                        r"(.+?)\s+in\s+(\d+\s*(?:minutes?|minute|hours?|hour|seconds?|second))\s*$",
                        body, re.IGNORECASE,
                    )
                    if m:
                        arguments["text"] = m.group(1).strip()
                        arguments["when"] = "in " + m.group(2)
                    else:
                        m2 = re.match(r"(.+?)\s+at\s+(\d{1,2}:\d{2}.*)$", body, re.IGNORECASE)
                        if m2:
                            arguments["text"] = m2.group(1).strip()
                            arguments["when"] = "at " + m2.group(2)
                        else:
                            arguments["text"] = body
                return ProviderResponse(
                    tool_calls=[ToolCall(id="off-0", name=tool_name, arguments=arguments)]
                )

        return ProviderResponse(
            text=(
                "I couldn't reach the local model just now — it didn't "
                "answer in time (it may still be loading, or busy on a "
                "long reply). I can still use local tools: ask for the "
                "time, a calculation, the weather, a web search, your "
                "notes or reminders, or the morning briefing. For "
                "anything else, try me again in a moment."
            )
        )
