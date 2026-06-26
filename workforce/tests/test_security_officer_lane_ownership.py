"""FAILING regression: the CISO (Lior) is BYPASSED for security items by a duplicated-ownership
overlap between the CTO lane and the security_officer's keywords.

When Lior (security_officer) was hired, ``agent_toolkit/collaboration.py`` added a
``_WORKER_KEYWORDS["security_officer"]`` pattern that includes the tokens ``security`` and
``incident``. But those two tokens were NOT removed from the pre-existing CTO LANE keyword set
(``LANE_KEYWORDS["cto"] = r"\\b(deploy|ci|pr|security|incident|build)\\b"``). The result is
DUPLICATED OWNERSHIP of the security domain:

  * ``_lane_target`` runs FIRST and resolves "security"/"incident" to the CTO lane (a C-suite owner).
  * the CEO's own-lane delegation to ``security_officer`` only happens when a security message uses a
    word that is in Lior's keywords but NOT in any lane keyword (e.g. "threat", "vuln", "ssrf").

So the MOST NATURAL security phrasings — the literal words "security" and "incident" — route to the
CTO instead of the dedicated CISO. And the CTO holds NO ``message:security_officer`` grant and Lior
is NOT a CTO report, so the item dead-ends at the CTO: Lior is never reached. This is the
"Lior <-> Lennox/CTO seam" / "no duplicated ownership" boundary the org design requires Lior to own.

CORRECT behavior: a security item the CEO raises (or that any sender raises in the security domain)
must be OWNED by the security_officer — either by removing the security tokens from the CTO lane so
``_lane_target`` no longer captures them, or by routing the security domain to Lior. The onboarding
test (tests/test_csuite_officers_onboarding.py::test_ceo_delegates_down_to_lior_on_a_security_item)
only passes because it deliberately phrases the message with "threat vuln secret rotation" — words
that dodge the CTO lane overlap — so it does not exercise this seam.

Loaded by path (deps-free CI venv), mirroring tests/test_org_collaboration.py.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


C = _load("collaboration", "agent_toolkit/collaboration.py")


class SecurityOfficerOwnsTheSecurityLane(unittest.TestCase):
    def setUp(self):
        C.load_org_chart(force=True)

    def test_no_token_is_owned_by_both_the_cto_lane_and_the_security_officer(self):
        """No duplicated ownership: a token in the security_officer's worker keywords must NOT also
        be a CTO LANE keyword, or the lane resolver captures the security domain before Lior."""
        cto_lane = set(re.findall(r"[a-z][a-z\- ]*[a-z]", C.LANE_KEYWORDS["cto"]))
        lior_kw = set(re.findall(r"[a-z][a-z\- ]*[a-z]", C._WORKER_KEYWORDS["security_officer"]))
        overlap = cto_lane & lior_kw
        self.assertEqual(
            overlap, set(),
            "duplicated ownership: token(s) appear in BOTH the CTO lane and the security_officer "
            f"keywords — the CTO lane will capture the security domain before Lior: {sorted(overlap)}",
        )

    def test_ceo_security_incident_item_is_delegated_to_lior_not_the_cto(self):
        """A CEO 'security incident' item must be delegated DOWN to the dedicated CISO (its report),
        not handed sideways to the CTO. Today the CTO lane keyword 'security'/'incident' wins and the
        item goes to the CTO, which holds no message:security_officer grant — so Lior is bypassed."""
        target, reason = C.route_collaboration(
            "decision: we have a security incident — assign an owner", from_role="ceo")
        self.assertEqual(
            target, "security_officer",
            f"a CEO security item routed to {target!r} ({reason}) instead of the CISO — the "
            "CTO-lane/security_officer keyword overlap bypasses Lior",
        )

    def test_a_plain_security_item_reaches_the_security_officer_somehow(self):
        """Whoever the router picks for a plain 'security incident' item, that target must be able to
        actually reach Lior — either it IS Lior, or it holds a message:security_officer grant. Today
        it is the CTO, who has neither, so the security item dead-ends and never reaches the CISO."""
        import yaml
        caps = yaml.safe_load((ROOT / "docs" / "governance" / "capabilities.yaml").read_text())

        def can_reach(role: str, target: str) -> bool:
            grant = (caps.get("grants") or {}).get(C.ROLE_TO_GRAPH.get(role, role)) or {}
            msg = {c["capability"].split(":", 1)[1]
                   for c in grant.get("capabilities", [])
                   if str(c.get("capability", "")).startswith("message:")}
            return C.ROLE_TO_GRAPH.get(target, target) in msg

        target, reason = C.route_collaboration(
            "decision: we have a security incident — assign an owner", from_role="ceo")
        reaches = target == "security_officer" or can_reach(target, "security_officer")
        self.assertTrue(
            reaches,
            f"router picked {target!r} ({reason}) for a security item, but {target!r} is not the "
            "security_officer and holds no message:security_officer grant — Lior is unreachable",
        )


if __name__ == "__main__":
    unittest.main()
