"""The brain: a real tool-use loop over a provider fallback chain.

Flow per user turn:
  1. Build messages: system prompt (identity, tools, memory facts, date/time)
     + recent conversation history + the new user message.
  2. Try providers in configured order until one answers.
  3. If the reply contains tool calls, execute them via the registry,
     append the observed results, and ask the provider again (up to
     MAX_STEPS). Tool results are reported as *observed* — a tool that
     fails returns its error text to the model instead of crashing.
  4. If every provider fails, the offline provider answers with local
     tools only (works with no API key and no model).
  5. Save the turn to memory; announce any due reminders.
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Any

from core.config import Config
from core.memory import Memory
from providers import build_provider_chain
from providers.base import BaseProvider, ProviderResponse
from providers.offline import OfflineProvider
from tools.registry import ToolRegistry

MAX_STEPS = 6

SYSTEM_PROMPT_TEMPLATE = """You are {name}, a personal AI assistant for {owner}.
You run locally on their computer (Windows or Linux) and you can act on it.

Rules:
- Use the tools you have when the user asks for something in the real world
  (search, weather, files, notes, reminders, system control). Do not guess
  facts you can look up — call a tool.
- Report what you OBSERVED from a tool result, not what you attempted.
  If a tool fails, say so plainly and offer the next best option.
- Be concise and helpful. Match the user's language (English, Roman Urdu,
  or Urdu script) unless they ask otherwise.
- Never reveal API keys, file paths of secrets, or the contents of .env.
- Dangerous actions (lock screen, shutdown, deleting files) need the user
  to confirm explicitly in the same conversation.
- You do not know the future. Weather, news and prices come from tools.

Today is {today}. Current time: {now}. Timezone: {tz}.
{context_block}
{assistant_facts}
Your tools: {tool_names}.
"""


class Brain:
    def __init__(
        self,
        config: Config,
        memory: Memory,
        registry: ToolRegistry,
        logger: logging.Logger | None = None,
    ):
        self.config = config
        self.memory = memory
        self.registry = registry
        self.logger = logger or logging.getLogger("jarvis.brain")
        self.providers: list[BaseProvider] = build_provider_chain(config)
        self.offline = OfflineProvider(config, registry)
        self.active_provider_name = "offline"
        # AmbientOS trust gate (Layer 1 wiring): every tool execution is
        # policy-checked via context-fabric before it runs. Construction
        # must never break the assistant — on any failure the gate is
        # disabled (mode off) and the failure is logged.
        self.trust_gate = None
        try:
            from core.trustgate import TrustGate

            self.trust_gate = TrustGate(config, self.logger)
        except Exception as exc:  # noqa: BLE001 - gate failure is data
            self.logger.warning("trust gate unavailable: %s", exc)

    # -- prompt ----------------------------------------------------------
    def _system_prompt(self) -> str:
        now = datetime.datetime.now()
        facts = self.memory.facts_summary()
        facts_block = (
            f"Things you remember about {self.config.owner}:\n{facts}"
            if facts
            else "You have no saved facts about the user yet."
        )
        # Live context: only what was actually detected, right now.
        context_block = ""
        try:
            from core.context import gather_context, render_context_block

            tasks = getattr(self, "task_manager", None)
            context_block = render_context_block(
                gather_context(self.config, self.memory, tasks=tasks)
            )
        except Exception:  # noqa: BLE001 - context is best-effort
            context_block = ""
        return SYSTEM_PROMPT_TEMPLATE.format(
            name=self.config.assistant_name,
            owner=self.config.owner,
            today=now.strftime("%A, %Y-%m-%d"),
            now=now.strftime("%H:%M:%S"),
            tz=self.config.timezone,
            context_block=context_block,
            assistant_facts=facts_block,
            tool_names=", ".join(t.name for t in self.registry.all_tools()),
        )

    def _messages(self, user_text: str) -> list[dict[str, Any]]:
        history = self.memory.recent_history(self.config.max_history)
        return (
            [{"role": "system", "content": self._system_prompt()}]
            + history
            + [{"role": "user", "content": user_text}]
        )

    # -- provider handling ------------------------------------------------
    def _chat_with_fallback(
        self, messages: list[dict[str, Any]], tools: list[dict]
    ) -> tuple[ProviderResponse, BaseProvider]:
        """Try providers in order; return the first successful response."""
        last_error: Exception | None = None
        for provider in self.providers:
            ok, _reason = provider.available()
            if not ok:
                continue
            try:
                resp = provider.chat(messages, tools)
                self.active_provider_name = provider.name
                return resp, provider
            except Exception as exc:  # noqa: BLE001 - fall through to next
                last_error = exc
                self.logger.warning(
                    "provider %s failed: %s", provider.name, exc
                )
        if last_error is not None:
            self.logger.warning("all providers failed (%s); going offline", last_error)
        resp = self.offline.chat(messages, tools)
        self.active_provider_name = "offline"
        return resp, self.offline

    # -- main entry -------------------------------------------------------
    def respond(self, user_text: str) -> str:
        user_text = user_text.strip()
        if not user_text:
            return "I didn't hear anything, sir."
        self.logger.info("user: %s", user_text)

        due = self.memory.due_reminders()
        messages = self._messages(user_text)
        tools = self.registry.schemas()
        reply = ""
        provider: BaseProvider | None = None

        for _step in range(MAX_STEPS):
            resp, provider = self._chat_with_fallback(messages, tools)
            if resp.text:
                reply = resp.text
            if not resp.tool_calls:
                break
            # One assistant message carrying all of this step's tool calls.
            messages.append(
                {
                    "role": "assistant",
                    "content": reply or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "name": call.name,
                            "arguments": call.arguments,
                        }
                        for call in resp.tool_calls
                    ],
                }
            )
            for call in resp.tool_calls:
                result = self._execute_gated(call.name, call.arguments)
                self.logger.info(
                    "tool %s(%s) -> %s",
                    call.name, call.arguments, result[:200],
                )
                messages.append(
                    {
                        "role": "tool",
                        "content": result,
                        "tool_call_id": call.id,
                        "name": call.name,
                    }
                )
            if provider is self.offline:
                # Offline provider has no second pass: render tool results.
                reply = self._render_offline_results(messages, user_text)
                break
        else:
            reply = reply or "I ran out of steps on that one, sir."

        if due:
            lines = []
            for r in due:
                self.memory.mark_reminder_done(r["id"])
                lines.append(f"⏰ Reminder: {r['text']}")
            reply = "\n".join(lines) + ("\n" + reply if reply else "")

        self.memory.add_message("user", user_text)
        self.memory.add_message("assistant", reply)
        self.logger.info("jarvis: %s", reply[:300])
        return reply

    def _render_offline_results(
        self, messages: list[dict[str, Any]], user_text: str
    ) -> str:
        results = [m["content"] for m in messages if m["role"] == "tool"]
        if not results:
            return (
                "I'm running offline right now (no provider available), "
                "so I can only use local tools. Try asking for the time, "
                "a calculation, the weather, a web search, or your notes "
                "and reminders."
            )
        return "\n".join(results)

    # -- one-shot helpers --------------------------------------------------
    def ask_llm(self, system: str, user: str) -> tuple[str | None, str]:
        """One LLM call without tools.

        Returns (text, provider_name), or (None, "offline") when no real
        provider answered. Used by tools that need the model directly
        (e.g. the coding doctor) instead of the full tool-use loop.
        """
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        resp, provider = self._chat_with_fallback(messages, [])
        if provider is self.offline or not (resp.text or "").strip():
            return None, "offline"
        return resp.text, provider.name

    def _execute_gated(self, name: str, arguments: dict | None) -> str:
        """Run a tool through the AmbientOS trust gate first.

        In enforce mode a policy DENY blocks execution and the denial
        reason is returned as the tool result, so the model can report
        it plainly. In audit mode (default) the verdict is logged to
        the Kyun? log and the tool still runs.
        """
        gate = getattr(self, "trust_gate", None)
        if gate is not None:
            verdict = gate.check(name, arguments)
            if not verdict.allowed:
                self.logger.info(
                    "trust gate BLOCKED %s: %s", name, verdict.reason
                )
                return (
                    f"Blocked by AmbientOS policy: {verdict.reason} "
                    "Tell the user plainly that this was not done, and why."
                )
        return self.registry.execute(name, arguments)

    def tool_result_text(self, name: str, arguments: dict) -> str:
        """Execute one tool directly (used by CLI --tool and GUI buttons)."""
        return self._execute_gated(name, arguments)
