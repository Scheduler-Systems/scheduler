"""Unit tests for the capability-grant gate (scripts/check_capability_coverage.py).

Covers the real manifest (must pass on the live 28-graph fleet) and every failure mode,
including a regression test per author-side bypass found by adversarial review (2026-06-06):
procurement-verb synonym evasion, quoted-truthy can_buy / auto_recharge, empty-owners
collapse, and unvalidated granted_by — plus the posture / issued_by / revocable / key-allowlist
hardening and the read:payroll false-fail fix.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Load the gate module by path (scripts/ is not a package).
_spec = importlib.util.spec_from_file_location(
    "check_capability_coverage", ROOT / "scripts" / "check_capability_coverage.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
validate = _mod.validate


def _real():
    graphs = set(json.loads((ROOT / "langgraph.json").read_text())["graphs"])
    manifest = yaml.safe_load((ROOT / "docs" / "governance" / "capabilities.yaml").read_text())
    return graphs, manifest


def _cap(capability="read:repo", scope="x", why="y", granted_by="shay", revocable=True):
    return {"capability": capability, "scope": scope, "why": why,
            "granted_by": granted_by, "revocable": revocable}


def _minimal():
    """A tiny, valid manifest + graph set for targeted failure-mode tests."""
    graphs = {"alpha"}
    manifest = {
        "owners": [{"id": "shay", "tier": "human", "role": "founder"}],
        "identities": {
            "model_inference": {"tier": "agent", "can_buy": False, "issued_by": "shay"},
            "github_app": {"tier": "agent", "can_buy": False, "issued_by": "shay"},
        },
        "funding": {"pool": {"auto_recharge": False, "ring_fenced": "pending"}},
        "grants": {
            "alpha": {
                "posture": "report_only",
                "can_buy": False,
                "funding": "pool",
                "identities": ["model_inference", "github_app"],
                "capabilities": [_cap()],
            }
        },
    }
    return graphs, manifest


def _errs(graphs, man):
    return validate(graphs, man)[0]


class RealManifest(unittest.TestCase):
    def test_real_manifest_passes(self):
        graphs, manifest = _real()
        errors, _ = validate(graphs, manifest)
        self.assertEqual(errors, [], f"real capabilities.yaml must pass the gate; got: {errors}")

    def test_every_deployed_graph_has_a_grant(self):
        graphs, manifest = _real()
        self.assertTrue(graphs.issubset(set(manifest["grants"])))


class FailureModes(unittest.TestCase):
    def setUp(self):
        self.graphs, self.man = _minimal()

    def test_minimal_is_valid(self):
        self.assertEqual(_errs(self.graphs, self.man), [])

    def test_missing_grant_fails(self):
        self.man["grants"].pop("alpha")
        self.assertTrue(any("NO capability grant" in e for e in _errs(self.graphs, self.man)))

    # --- Rule #1 -----------------------------------------------------------------
    def test_human_identity_reference_fails(self):
        self.man["grants"]["alpha"]["identities"].append("shay")
        self.assertTrue(any("HUMAN identity" in e and "Rule #1" in e for e in _errs(self.graphs, self.man)))

    def test_empty_owners_blocked(self):  # adversary BYPASS: empty owners collapses human set
        self.man["owners"] = []
        self.assertTrue(any("owners is missing/empty" in e for e in _errs(self.graphs, self.man)))

    def test_missing_owners_blocked(self):
        self.man.pop("owners")
        self.assertTrue(any("owners is missing/empty" in e for e in _errs(self.graphs, self.man)))

    def test_owner_relabeled_agent_collapses_human_set(self):
        # delete owners + reference 'shay' as an agent identity → must NOT pass
        self.man.pop("owners")
        self.man["identities"]["shay"] = {"tier": "agent", "can_buy": False, "issued_by": "shay"}
        self.man["grants"]["alpha"]["identities"].append("shay")
        self.assertNotEqual(_errs(self.graphs, self.man), [])

    def test_issued_by_must_be_human(self):
        self.man["identities"]["model_inference"]["issued_by"] = "mallory"
        self.assertTrue(any("issuance chain broken" in e for e in _errs(self.graphs, self.man)))

    def test_missing_issued_by_fails(self):
        self.man["identities"]["model_inference"].pop("issued_by")
        self.assertTrue(any("must declare issued_by" in e for e in _errs(self.graphs, self.man)))

    def test_granted_by_non_owner_fails(self):  # adversary BYPASS: forged grantor
        self.man["grants"]["alpha"]["capabilities"][0]["granted_by"] = "mallory"
        self.assertTrue(any("not a human owner" in e for e in _errs(self.graphs, self.man)))

    def test_granted_by_self_grant_fails(self):  # adversary BYPASS: agent self-grants
        self.man["grants"]["alpha"]["capabilities"][0]["granted_by"] = "model_inference"
        self.assertTrue(any("not a human owner" in e for e in _errs(self.graphs, self.man)))

    # --- spend-only --------------------------------------------------------------
    def test_can_buy_true_fails(self):
        self.man["grants"]["alpha"]["can_buy"] = True
        self.assertTrue(any("can_buy" in e for e in _errs(self.graphs, self.man)))

    def test_quoted_truthy_can_buy_blocked(self):  # adversary BYPASS: can_buy:"Y"/"1"/"enabled"
        for v in ("Y", "1", "yes ", "True", "enabled", 1):
            self.man["grants"]["alpha"]["can_buy"] = v
            self.assertTrue(any("can_buy must be the boolean false" in e for e in _errs(self.graphs, self.man)),
                            f"can_buy={v!r} should fail")

    def test_missing_can_buy_fails(self):
        self.man["grants"]["alpha"].pop("can_buy")
        self.assertTrue(any("must declare can_buy" in e for e in _errs(self.graphs, self.man)))

    def test_identity_can_buy_truthy_fails(self):
        self.man["identities"]["model_inference"]["can_buy"] = "yes"
        self.assertTrue(any("can_buy must be the boolean false" in e for e in _errs(self.graphs, self.man)))

    def test_procurement_synonym_blocked(self):  # adversary BYPASS: blocklist synonyms
        for verb in ("buy:tokens", "acquire:capacity", "fund:pool", "settle:invoice",
                     "remit:vendor", "subscribe:plan", "execute:deploy", "deploy:prod"):
            self.man["grants"]["alpha"]["capabilities"] = [_cap(capability=verb)]
            self.assertTrue(any("not allow-listed" in e for e in _errs(self.graphs, self.man)),
                            f"verb {verb!r} should be blocked by the allow-list")

    def test_allowlisted_verbs_pass(self):
        for verb in ("read:repo", "post:slack", "propose:draft", "write:github_issue", "git:prune_merged"):
            self.man["grants"]["alpha"]["capabilities"] = [_cap(capability=verb)]
            self.assertEqual(_errs(self.graphs, self.man), [], f"verb {verb!r} should pass")

    def test_read_payroll_not_false_failed(self):  # false-fail fix: 'pay' substring no longer trips
        self.man["grants"]["alpha"]["capabilities"] = [_cap(capability="read:payroll")]
        self.assertEqual(_errs(self.graphs, self.man), [])

    # --- funding -----------------------------------------------------------------
    def test_auto_recharge_without_ringfence_fails(self):
        self.man["funding"]["pool"] = {"auto_recharge": True, "ring_fenced": False}
        self.assertTrue(any("auto_recharge is ON but not ring_fenced" in e for e in _errs(self.graphs, self.man)))

    def test_auto_recharge_with_ringfence_ok(self):
        self.man["funding"]["pool"] = {"auto_recharge": True, "ring_fenced": True}
        self.assertEqual(_errs(self.graphs, self.man), [])

    def test_quoted_truthy_auto_recharge_blocked(self):  # adversary BYPASS: auto_recharge:"ON"
        for v in ("ON", "yes", "1", "true"):
            self.man["funding"]["pool"] = {"auto_recharge": v, "ring_fenced": False}
            self.assertTrue(any("must be a real boolean" in e for e in _errs(self.graphs, self.man)),
                            f"auto_recharge={v!r} should fail")

    def test_undeclared_funding_reference_fails(self):
        self.man["grants"]["alpha"]["funding"] = "no_such_pool"
        self.assertTrue(any("not a declared instrument" in e for e in _errs(self.graphs, self.man)))

    def test_pending_ringfence_is_warning_not_error(self):
        errors, warnings = validate(self.graphs, self.man)
        self.assertEqual(errors, [])
        self.assertTrue(any("ring_fenced: pending" in w for w in warnings))

    # --- posture / keys / scope / schema ----------------------------------------
    def test_posture_must_be_report_only(self):  # the execute-guard
        self.man["grants"]["alpha"]["posture"] = "execute"
        self.assertTrue(any("posture must be report_only" in e for e in _errs(self.graphs, self.man)))

    def test_missing_posture_fails(self):
        self.man["grants"]["alpha"].pop("posture")
        self.assertTrue(any("posture must be report_only" in e for e in _errs(self.graphs, self.man)))

    def test_forbidden_grant_key_blocked(self):  # identity-smuggling channel
        self.man["grants"]["alpha"]["acts_as"] = "shay"
        self.assertTrue(any("forbidden key" in e for e in _errs(self.graphs, self.man)))

    def test_unknown_grant_key_blocked(self):
        self.man["grants"]["alpha"]["sneaky"] = 1
        self.assertTrue(any("unknown key" in e for e in _errs(self.graphs, self.man)))

    def test_wildcard_scope_blocked(self):
        for w in ("*", "all", "everything", ""):
            self.man["grants"]["alpha"]["capabilities"] = [_cap(scope=w)]
            self.assertNotEqual(_errs(self.graphs, self.man), [], f"wildcard scope {w!r} should fail")

    def test_revocable_required(self):
        self.man["grants"]["alpha"]["capabilities"] = [_cap(revocable=False)]
        self.assertTrue(any("revocable: true" in e for e in _errs(self.graphs, self.man)))

    def test_missing_required_cap_field_fails(self):
        del self.man["grants"]["alpha"]["capabilities"][0]["why"]
        self.assertTrue(any("missing 'why'" in e for e in _errs(self.graphs, self.man)))

    def test_no_capabilities_fails(self):
        self.man["grants"]["alpha"]["capabilities"] = []
        self.assertTrue(any("no capabilities" in e for e in _errs(self.graphs, self.man)))

    def test_no_identities_fails(self):
        self.man["grants"]["alpha"]["identities"] = []
        self.assertTrue(any("no identities" in e for e in _errs(self.graphs, self.man)))

    def test_undeclared_identity_fails(self):
        self.man["grants"]["alpha"]["identities"].append("ghost_key")
        self.assertTrue(any("undeclared identity" in e for e in _errs(self.graphs, self.man)))

    def test_identity_must_be_agent_tier(self):
        self.man["identities"]["model_inference"]["tier"] = "human"
        self.assertTrue(any("must be tier: agent" in e for e in _errs(self.graphs, self.man)))

    def test_owner_must_be_human_tier(self):
        self.man["owners"][0]["tier"] = "agent"
        self.assertTrue(any("must be tier: human" in e for e in _errs(self.graphs, self.man)))


if __name__ == "__main__":
    unittest.main()
