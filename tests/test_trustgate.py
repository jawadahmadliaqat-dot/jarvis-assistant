"""Trust gate tests — AmbientOS Layer 1 wiring (no network, no keys).

Run from the project root:
    python -m unittest tests.test_trustgate -v

The mapping test always runs. The policy tests need context-fabric
(Layer 2) importable — set CONTEXT_FABRIC_PATH to a checkout of the
Context-fabric repo (in the ambience-os layout it is found
automatically as ../context-fabric). Without it they skip.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _config(tmp: str, mode: str = "enforce", role: str = "OWNER"):
    from core.config import Config

    return Config(
        {
            "paths": {"data_dir": tmp},
            "ambient": {"trust_gate": mode, "user_role": role},
        }
    )


class MappingTest(unittest.TestCase):
    def test_every_registered_tool_is_mapped(self):
        import logging

        from core.trustgate import TOOL_INTENTS
        from tools.registry import ToolRegistry, load_all_tools

        reg = ToolRegistry(logging.getLogger("test.mapping"))
        load_all_tools(reg, {"data_dir": tempfile.mkdtemp()})
        names = [t.name for t in reg.all_tools()]
        self.assertGreaterEqual(len(names), 37)
        unmapped = [n for n in names if n not in TOOL_INTENTS]
        self.assertEqual(unmapped, [], f"unmapped tools: {unmapped}")


class GateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        from core.trustgate import TrustGate

        self._TrustGate = TrustGate
        probe = TrustGate(_config(self.tmp))
        if probe._fabric is None:
            self.skipTest("context-fabric not importable (set CONTEXT_FABRIC_PATH)")

    def gate(self, mode="enforce", role="OWNER"):
        return self._TrustGate(_config(self.tmp, mode, role))

    def test_owner_can_control_volume(self):
        v = self.gate(role="OWNER").check("set_volume", {"level": 40})
        self.assertEqual(v.decision, "ALLOW")
        self.assertTrue(v.allowed)
        self.assertEqual(v.capability, "system.control")

    def test_guest_cannot_control_volume(self):
        v = self.gate(role="GUEST").check("set_volume", {"level": 40})
        self.assertEqual(v.decision, "DENY")
        self.assertFalse(v.allowed)

    def test_guest_can_read_weather(self):
        v = self.gate(role="GUEST").check("get_weather", {"city": "Lahore"})
        self.assertEqual(v.decision, "ALLOW")
        self.assertTrue(v.allowed)

    def test_unknown_cannot_write_notes(self):
        v = self.gate(role="UNKNOWN").check("add_note", {"text": "hi"})
        self.assertEqual(v.decision, "DENY")
        self.assertFalse(v.allowed)

    def test_lock_screen_needs_confirmation_even_for_owner(self):
        g = self.gate(role="OWNER")
        v = g.check("lock_screen", {})
        self.assertEqual(v.decision, "DENY")
        self.assertFalse(v.allowed)
        v2 = g.check("lock_screen", {"confirm": True})
        self.assertEqual(v2.decision, "ALLOW")
        self.assertTrue(v2.allowed)

    def test_audit_mode_logs_but_never_blocks(self):
        v = self.gate(mode="audit", role="GUEST").check("set_volume", {"level": 10})
        self.assertEqual(v.decision, "DENY")   # the policy verdict itself
        self.assertTrue(v.allowed)             # but audit never blocks

    def test_kyun_log_written(self):
        g = self.gate(role="GUEST")
        g.check("get_weather", {"city": "Lahore"})
        g.check("set_volume", {"level": 10})
        lines = (Path(self.tmp) / "ambient_kyun.jsonl").read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)
        entries = [json.loads(x) for x in lines]
        self.assertEqual(entries[0]["decision"], "ALLOW")
        self.assertEqual(entries[1]["decision"], "DENY")
        self.assertIn("reason", entries[1])
        self.assertEqual(entries[1]["tool"], "set_volume")

    def test_tampered_and_expired_tokens_fail_verification(self):
        from datetime import datetime, timedelta, timezone

        gate = self.gate(role="OWNER")
        _PE, _TG, verify_token, key = gate._fabric
        intent = {"actor_role": "OWNER", "action": "Control", "resource": "System"}
        token = gate._generator.generate(intent, gate._facts())
        self.assertEqual(token["decision"], "ALLOW")
        ok, _ = verify_token(token, key=key)
        self.assertTrue(ok)
        forged = dict(token)
        forged["user_role"] = "GUEST"
        ok, why = verify_token(forged, key=key)
        self.assertFalse(ok)
        self.assertIn("signature", why)
        future = datetime.now(timezone.utc) + timedelta(seconds=3600)
        ok, why = verify_token(token, key=key, now=future)
        self.assertFalse(ok)
        self.assertIn("expired", why)


if __name__ == "__main__":
    unittest.main()
