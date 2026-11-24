"""AmbientOS Trust Gate — Layer 1 (Jarvis) wiring to Layer 2 + Layer 3.

This is the orchestrator piece of AmbientOS ("The Invisible, Trusted
Computer"). Jarvis's brain never executes a tool directly any more:
every tool call passes through this gate first, in the stack's order —

    Decide (the model proposes a tool call)
      -> Policy   (context-fabric, Layer 2: signed policy_decision)
      -> Verify   (software-trust style checks, Layer 3: token signature
                   + expiry, capability membership, device manifest)
      -> Act      (the tool runs — or does not)

Responsibilities that live HERE, in Layer 1, by the owner's ruling
(2026-10-30, mismatch M1): the semantic mapping from Jarvis tool names
to (action, resource) policy intents is the orchestrator's job. Layer 2
evaluates policies; Layer 3's contract is not extended; no field is
invented — intents use context-fabric's existing {actor_role, action,
resource} shape and tokens are context-fabric's policy_decision dicts.

context-fabric is loaded, in order, from:
  1. $CONTEXT_FABRIC_PATH (directory containing the context_fabric pkg)
  2. ../context-fabric relative to this repo (the ambience-os layout:
     layers/jarvis-assistant next to layers/context-fabric)
  3. an installed `context_fabric` package

If context-fabric cannot be loaded the gate degrades honestly: it logs
FABRIC_UNAVAILABLE, and in enforce mode the manifest's sensitive tools
still require explicit confirmation while other tools are allowed with
the gap logged. Signing uses context-fabric's documented dev scheme
(SAMPLE_DEV_KEY unless CONTEXT_FABRIC_SIGNING_KEY is set) — the same
documented limitation as the fabric itself; production needs real key
management.

Modes (config: ambient.trust_gate):
  off     — no checks, no log (legacy behaviour)
  audit   — decide + verify + log everything, never block (DEFAULT)
  enforce — a DENY verdict blocks the tool call

Every verdict (audit + enforce) is appended as one JSON line to
<data_dir>/ambient_kyun.jsonl — the PC analogue of the Ambience
"Kyun?" reason log: what was asked, which capability, which decision,
and why.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# M1 mapping — Jarvis tool -> (action, resource). Owned by Layer 1.
# Capability string (context-fabric derive_capability fallback shape):
#   f"{resource.lower()}.{action.lower()}"
# ---------------------------------------------------------------------------

TOOL_INTENTS: dict[str, tuple[str, str]] = {
    # Read
    "get_weather": ("Read", "Weather"),
    "get_time": ("Read", "Time"),
    "get_date": ("Read", "Time"),
    "web_search": ("Read", "Web"),
    "search_news": ("Read", "News"),
    "search_files": ("Read", "Files"),
    "read_file": ("Read", "Files"),
    "list_directory": ("Read", "Files"),
    "list_notes": ("Read", "Notes"),
    "search_notes": ("Read", "Notes"),
    "list_reminders": ("Read", "Reminders"),
    "list_routines": ("Read", "Routines"),
    "list_research_reports": ("Read", "Research"),
    "list_timers": ("Read", "Timers"),
    "clipboard_paste": ("Read", "Clipboard"),
    "system_info": ("Read", "System"),
    "check_alerts": ("Read", "Alerts"),
    "morning_briefing": ("Read", "Briefing"),
    "evening_summary": ("Read", "Briefing"),
    "say_hello": ("Read", "Social"),
    "git_status": ("Read", "Files"),
    "git_diff": ("Read", "Files"),
    # Write
    "add_note": ("Write", "Notes"),
    "write_file": ("Write", "Files"),
    "edit_file": ("Write", "Files"),
    "git_commit": ("Write", "Files"),
    "remember_fact": ("Write", "Memory"),
    "add_reminder": ("Write", "Reminders"),
    "clipboard_copy": ("Write", "Clipboard"),
    "start_timer": ("Write", "Timers"),
    # Delete
    "delete_note": ("Delete", "Notes"),
    # Control
    "set_volume": ("Control", "System"),
    "set_brightness": ("Control", "System"),
    "media_control": ("Control", "Media"),
    "lock_screen": ("Control", "Screen"),
    "take_screenshot": ("Control", "Screen"),
    "open_app": ("Control", "Apps"),
    "open_website": ("Control", "Web"),
    "run_routine": ("Control", "Routines"),
    # Execute
    "calculate": ("Execute", "Calculator"),
    "deep_research": ("Execute", "Research"),
    "fix_error": ("Execute", "Code"),
    "run_command": ("Execute", "System"),
    "run_tests": ("Execute", "Code"),
}


def capability_for(tool_name: str) -> str | None:
    intent = TOOL_INTENTS.get(tool_name)
    if intent is None:
        return None
    action, resource = intent
    return f"{resource.lower()}.{action.lower()}"


@dataclass
class GateVerdict:
    allowed: bool            # may the tool actually run (mode-aware)
    decision: str            # ALLOW | DENY (the policy verdict itself)
    reason: str
    tool: str
    capability: str | None = None
    policy_ids: list[str] = field(default_factory=list)


def _load_fabric():
    """Return (PolicyEvaluator, TokenGenerator, verify_token, key) or None."""
    candidates: list[Path] = []
    env_path = os.environ.get("CONTEXT_FABRIC_PATH")
    if env_path:
        candidates.append(Path(env_path))
    repo_root = Path(__file__).resolve().parent.parent
    candidates.append(repo_root.parent / "context-fabric")   # ambience-os layout
    candidates.append(repo_root / "vendor" / "context-fabric")
    for cand in candidates:
        if (cand / "context_fabric" / "__init__.py").exists():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            break
    try:
        evaluator_mod = importlib.import_module("context_fabric.evaluator")
        token_mod = importlib.import_module("context_fabric.token")
    except Exception:
        return None
    try:
        key = token_mod.resolve_key()
    except Exception:
        # Documented dev scheme fallback (context-fabric's SAMPLE_DEV_KEY).
        key = getattr(token_mod, "SAMPLE_DEV_KEY", "context-fabric-dev-sample-key")
        if isinstance(key, str):
            key = key.encode("utf-8")
    return evaluator_mod.PolicyEvaluator, token_mod.TokenGenerator, token_mod.verify_token, key


class TrustGate:
    def __init__(
        self,
        config,
        logger: logging.Logger | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger("jarvis.trustgate")
        self.mode = str(config.get("ambient", "trust_gate", default="audit")).lower()
        if self.mode not in ("off", "audit", "enforce"):
            self.logger.warning("unknown trust_gate mode %r; using audit", self.mode)
            self.mode = "audit"
        self.role = str(config.get("ambient", "user_role", default="OWNER")).upper()
        self.user_present = bool(config.get("ambient", "user_present", default=True))
        self.ambient_state = str(config.get("ambient", "state", default="HOME")).upper()
        self.ttl = int(config.get("ambient", "token_ttl_seconds", default=60))
        self.data_dir = Path(config.data_dir)
        self.kyun_path = self.data_dir / "ambient_kyun.jsonl"

        root = Path(__file__).resolve().parent.parent
        self._policies_path = root / "ambient" / "policies.json"
        self._manifest_path = root / "ambient" / "manifest.json"
        try:
            self._sensitive: dict[str, str] = json.loads(
                self._manifest_path.read_text(encoding="utf-8")
            ).get("sensitive_tools", {})
        except Exception:
            self._sensitive = {}

        self._fabric = _load_fabric()
        self._generator = None
        if self._fabric is not None:
            PolicyEvaluator, TokenGenerator, _verify, key = self._fabric
            try:
                evaluator = PolicyEvaluator.from_file(self._policies_path)
                self._generator = TokenGenerator(evaluator, ttl_seconds=self.ttl, key=key)
            except Exception as exc:  # policies unreadable -> fabric unusable
                self.logger.warning("trust gate: policies unusable: %s", exc)
                self._fabric = None
        if self._fabric is None and self.mode != "off":
            self.logger.warning(
                "trust gate: context-fabric not loadable; running degraded "
                "(see core/trustgate.py docstring)"
            )

    # -- context ------------------------------------------------------------

    def _facts(self) -> dict[str, Any]:
        hour = datetime.now().hour
        if hour < 5:
            tod = "NIGHT"
        elif hour < 12:
            tod = "MORNING"
        elif hour < 17:
            tod = "DAY"
        elif hour < 21:
            tod = "EVENING"
        else:
            tod = "NIGHT"
        return {
            "user_role": self.role,
            "user_present": self.user_present,
            "ambient_state": self.ambient_state,
            "time_of_day": tod,
        }

    # -- the gate -------------------------------------------------------------

    def check(self, tool_name: str, arguments: dict | None) -> GateVerdict:
        args = dict(arguments or {})
        capability = capability_for(tool_name)
        if self.mode == "off":
            return GateVerdict(True, "ALLOW", "trust gate off", tool_name, capability)

        verdict = self._decide(tool_name, args, capability)
        allowed = verdict.allowed or self.mode == "audit"
        self._log_kyun(verdict, args)
        return GateVerdict(allowed, verdict.decision, verdict.reason,
                           tool_name, capability, verdict.policy_ids)

    def _decide(self, tool_name: str, args: dict, capability: str | None) -> GateVerdict:
        # Manifest (Layer 3 analogue): sensitive tools need confirm=true.
        if tool_name in self._sensitive and args.get("confirm") is not True:
            return GateVerdict(
                False, "DENY",
                f"'{tool_name}' is sensitive ({self._sensitive[tool_name]}); "
                "explicit user confirmation (confirm=true) is required first.",
                tool_name, capability)

        if capability is None:
            return GateVerdict(
                False, "DENY",
                f"tool '{tool_name}' has no capability mapping in Layer 1 (M1 map); "
                "unmapped tools are denied in the trust gate.",
                tool_name, None)

        if self._fabric is None or self._generator is None:
            return GateVerdict(
                True, "ALLOW",
                "FABRIC_UNAVAILABLE: context-fabric not loadable; allowed in "
                "degraded mode (manifest checks still applied above).",
                tool_name, capability)

        _PE, _TG, verify_token, key = self._fabric
        action, resource = TOOL_INTENTS[tool_name]
        intent = {"actor_role": self.role, "action": action, "resource": resource}
        token = self._generator.generate(intent, self._facts())

        if token.get("decision") != "ALLOW":
            return GateVerdict(
                False, "DENY",
                f"context-fabric DENY: {token.get('reason', 'no reason given')}",
                tool_name, capability,
                list(token.get("matched_forbid_ids", [])))

        ok, why = verify_token(token, key=key)
        if not ok:
            return GateVerdict(
                False, "DENY",
                f"policy token failed verification: {why}",
                tool_name, capability,
                list(token.get("matched_permit_ids", [])))

        caps = token.get("allowed_capabilities", [])
        if "*" not in caps and capability not in caps:
            return GateVerdict(
                False, "DENY",
                f"capability '{capability}' not in token's allowed_capabilities {caps}.",
                tool_name, capability,
                list(token.get("matched_permit_ids", [])))

        return GateVerdict(
            True, "ALLOW",
            f"context-fabric ALLOW (policies: {', '.join(token.get('matched_permit_ids', []))}); "
            "token signature + expiry verified; capability in token.",
            tool_name, capability,
            list(token.get("matched_permit_ids", [])))

    # -- Kyun? log --------------------------------------------------------------

    def _log_kyun(self, verdict: GateVerdict, args: dict) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tool": verdict.tool,
            "capability": verdict.capability,
            "decision": verdict.decision,
            "executed": verdict.allowed,
            "mode": self.mode,
            "role": self.role,
            "reason": verdict.reason,
            "policy_ids": verdict.policy_ids,
        }
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with self.kyun_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:  # the log must never break the tool loop
            self.logger.warning("trust gate: Kyun log write failed: %s", exc)
