"""Unit tests for scripts/provision_identity.py — the per-agent identity generator.

These prove the security-critical invariants of constitution §3 (per-agent least-privilege
identity) IN CODE, deps-free (only stdlib + pyyaml, loaded by path like the rest of the suite):

  * FAIL-CLOSED: a roster row with no class defaults to the most restrictive class; a row
    with an UNKNOWN class is an error (never invent/widen access).
  * ISOLATION: an agent's Vault policy references ONLY its own secret subtree — never another
    agent's. One leaked AppRole cannot read a peer's secrets (blast-radius containment).
  * NO WRITE: no class ever emits a Vault write/create/delete/sudo capability — the
    agent-write boundary (VAULT-ACCESS.md §6) stays closed for every agent.
  * PROVISION is ops-only: the `identity:provision` capability belongs to exactly one class.
  * IDEMPOTENT: same inputs → byte-identical artifacts (safe to re-run in CI / by the agent).
  * COVERAGE: every deployed+rostered agent in the REAL roster maps to a known class.
"""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("provision_identity", ROOT / "scripts" / "provision_identity.py")
pi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pi)


REGISTRY = pi.load_registry()


class ResolveClass(unittest.TestCase):
    def test_missing_class_defaults_to_floor(self):
        cls, used_default = pi.resolve_class("x", {}, REGISTRY)
        self.assertEqual(cls, REGISTRY["meta"]["default_class"])
        self.assertTrue(used_default)

    def test_default_floor_is_the_most_restrictive(self):
        # the floor must have no extra reads and no capabilities — the genuine least-privilege.
        floor = REGISTRY["classes"][REGISTRY["meta"]["default_class"]]
        self.assertEqual(floor.get("extra_vault_read", []), [])
        self.assertEqual(floor.get("capabilities", []), [])

    def test_unknown_class_is_fail_closed_error(self):
        with self.assertRaises(pi.UnknownClassError):
            pi.resolve_class("x", {"privilege_class": "root-everything"}, REGISTRY)

    def test_known_class_resolves(self):
        cls, used_default = pi.resolve_class("cfo", {"privilege_class": "finance-reader"}, REGISTRY)
        self.assertEqual(cls, "finance-reader")
        self.assertFalse(used_default)


class PolicyScoping(unittest.TestCase):
    def test_policy_grants_only_read(self):
        # NO class may ever emit a write/create/update/delete/sudo/list capability.
        forbidden = ("create", "update", "delete", "sudo", "list", "patch")
        for cls in REGISTRY["classes"]:
            hcl = pi.vault_policy_hcl("any_agent", cls, REGISTRY)
            self.assertIn('capabilities = ["read"]', hcl)
            for cap in forbidden:
                self.assertNotIn(cap, hcl, f"class {cls} leaked a {cap!r} capability")

    def test_policy_isolation_no_cross_agent_paths(self):
        # alice's policy must reference alice's subtree and NEVER bob's.
        alice = pi.vault_policy_hcl("alice", "ops-provisioner", REGISTRY)
        self.assertIn("secret/data/gal-run/agents/alice/*", alice)
        self.assertNotIn("agents/bob/", alice)

    def test_every_agent_can_read_its_own_subtree_and_shared(self):
        hcl = pi.vault_policy_hcl("zeta", "read-only", REGISTRY)
        self.assertIn("secret/data/gal-run/agents/zeta/*", hcl)
        self.assertIn("secret/data/gal-run/shared/model-keys", hcl)
        self.assertIn("secret/data/gal-run/shared/langfuse-ingest", hcl)

    def test_finance_reader_adds_billing_read_only(self):
        hcl = pi.vault_policy_hcl("cfo", "finance-reader", REGISTRY)
        self.assertIn("secret/data/gal-run/shared/billing-readonly", hcl)
        # but it must NOT grant a billing WRITE path
        self.assertNotIn("billing-write", hcl)


class Capabilities(unittest.TestCase):
    def test_provision_capability_is_ops_only(self):
        owners = [c for c, d in REGISTRY["classes"].items()
                  if "identity:provision" in (d.get("capabilities") or [])]
        self.assertEqual(owners, ["ops-provisioner"],
                         "exactly one class may mint identities (the recursion base)")

    def test_no_class_grants_a_billing_write_or_deploy(self):
        for cls, d in REGISTRY["classes"].items():
            caps = d.get("capabilities") or []
            for bad in ("billing:write", "deploy", "prod-write", "vault:write"):
                self.assertNotIn(bad, caps, f"class {cls} must not grant {bad}")


class Artifacts(unittest.TestCase):
    def test_build_is_idempotent(self):
        row = {"privilege_class": "governance-auditor"}
        a = pi.build_artifacts("board_chair", row, REGISTRY)
        b = pi.build_artifacts("board_chair", row, REGISTRY)
        self.assertEqual(a, b)

    def test_service_account_records_class(self):
        arts = pi.build_artifacts("git_maintainer", {"privilege_class": "repo-contributor"}, REGISTRY)
        self.assertIn("repo-contributor", arts["service-account.yaml"])
        self.assertIn("agent-git_maintainer", arts["service-account.yaml"])

    def test_apply_plan_never_executes_only_describes(self):
        # the apply plan is text the operator runs — it must contain vault/kubectl as STRINGS,
        # and the generator must not import subprocess (it never shells out).
        import inspect
        src = inspect.getsource(pi)
        self.assertNotIn("subprocess", src)
        self.assertNotIn("os.system", src)
        plan = "\n".join(pi.apply_plan("cfo", "finance-reader", REGISTRY))
        self.assertIn("vault policy write", plan)
        self.assertIn("kubectl apply", plan)


class RealRosterCoverage(unittest.TestCase):
    def test_every_deployed_agent_maps_to_a_known_class(self):
        # the REAL roster + registry: no deployed+rostered agent may reference an unknown class.
        registry = pi.load_registry()
        roster = pi.load_roster()
        graphs = pi.deployed_graphs()
        for agent in sorted(n for n in roster if n in graphs):
            # must not raise UnknownClassError
            cls, _ = pi.resolve_class(agent, roster[agent] or {}, registry)
            self.assertIn(cls, registry["classes"])


if __name__ == "__main__":
    unittest.main()
