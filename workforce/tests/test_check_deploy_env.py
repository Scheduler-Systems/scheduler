"""FINDING 2 + 3 — the deploy-env preflight reports SECRET NAMES (never values) and flags the
write-gate half-config.

check_deploy_env is the LOUD operator preflight: it groups the required/optional deployment
secrets (LangSmith, GitHub-webhook, Gmail/Morning, Slack), reports each as set/unset BY NAME ONLY,
and flags the write-gate misconfig (allowlist set + floor still on, or floor lifted + allowlist
empty). These tests assert:
  * NEVER a secret VALUE in the report (names + booleans only) — the cardinal safety property;
  * grouping is correct (the four named groups, with required/optional + any-of semantics);
  * the write-gate misconfig is detected in BOTH half-config directions, and a coordinated config
    is clean; the TIER1 first wave is surfaced;
  * exit-code policy: 1 on required-incomplete OR misconfig; 0 when required complete + coordinated;
    --strict also fails on optional-incomplete.
All env is patched with ``clear=True`` so the test is hermetic (no ambient secret leaks in).
"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from scripts import check_deploy_env as cde

# Sentinel secret VALUES — if any of these strings appears in any report output, that is a LEAK.
_GH_VAL = "ghs_SENTINEL_WEBHOOK_VALUE_AAA"
_SENTRY_VAL = "sntry_SENTINEL_CLIENT_VALUE_BBB"
_LS_KEY = "lsv2_sk_SENTINEL_API_KEY_CCC"
_SLACK_VAL = "xoxb-SENTINEL_BOT_TOKEN_DDD"
_GMAIL_VAL = "ya29.SENTINEL_OAUTH_TOKEN_EEE"
_SENTINELS = (_GH_VAL, _SENTRY_VAL, _LS_KEY, _SLACK_VAL, _GMAIL_VAL)

_FULL_ENV = {
    "LANGGRAPH_DEPLOYMENT_URL": "https://example.invalid",
    "LANGSMITH_API_KEY": _LS_KEY,
    "LANGSMITH_TENANT_ID": "tenant-xyz",
    "GITHUB_WEBHOOK_SECRET": _GH_VAL,
    "SENTRY_CLIENT_SECRET": _SENTRY_VAL,
    "GMAIL_OAUTH_TOKEN": _GMAIL_VAL,
    "MORNING_PERSONAL_EMAIL": "p@example.invalid",
    "MORNING_COMPANY_EMAIL": "c@example.invalid",
    "SLACK_BOT_TOKEN": _SLACK_VAL,
}


def _collect(env: dict) -> dict:
    with mock.patch.dict(os.environ, env, clear=True):
        return cde.collect()


def _main_output(argv, env):
    """Run main() capturing stdout + exit code under a hermetic env."""
    import contextlib
    import io
    buf = io.StringIO()
    with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(buf):
        rc = cde.main(argv)
    return rc, buf.getvalue()


class NamesNeverValues(unittest.TestCase):
    def test_no_secret_value_in_human_report(self):
        rc, out = _main_output([], _FULL_ENV)
        for sentinel in _SENTINELS:
            self.assertNotIn(sentinel, out, f"LEAK: secret value {sentinel!r} printed in report")

    def test_no_secret_value_in_json_report(self):
        rc, out = _main_output(["--json"], _FULL_ENV)
        for sentinel in _SENTINELS:
            self.assertNotIn(sentinel, out, f"LEAK: secret value {sentinel!r} printed in --json")
        # the JSON must still NAME the vars (so the operator knows what is set).
        parsed = json.loads(out)
        names = {m["name"] for g in parsed["groups"] for m in [{"name": n} for n in (g["set"] + g["missing"])]}
        self.assertIn("GITHUB_WEBHOOK_SECRET", names)
        self.assertIn("LANGSMITH_API_KEY", names)

    def test_report_reports_set_vs_missing_by_name(self):
        env = {"LANGGRAPH_DEPLOYMENT_URL": "u", "LANGSMITH_API_KEY": _LS_KEY}  # tenant missing
        report = _collect(env)
        ls = next(g for g in report["groups"] if g["group"] == "LangSmith")
        self.assertIn("LANGSMITH_API_KEY", ls["set"])
        self.assertIn("LANGSMITH_TENANT_ID", ls["missing"])
        self.assertFalse(ls["complete"])  # 'all' group with a missing var is incomplete


class Grouping(unittest.TestCase):
    def test_four_named_groups(self):
        report = _collect({})
        groups = {g["group"] for g in report["groups"]}
        self.assertEqual(groups, {"LangSmith", "GitHub-webhook", "Gmail/Morning", "Slack"})

    def test_required_vs_optional(self):
        report = _collect({})
        req = {g["group"] for g in report["groups"] if g["required"]}
        self.assertEqual(req, {"LangSmith", "GitHub-webhook"})

    def test_any_of_group_complete_with_one_set(self):
        # GitHub-webhook is any-of: ONE of the two secrets satisfies it.
        report = _collect({"GITHUB_WEBHOOK_SECRET": _GH_VAL})
        gh = next(g for g in report["groups"] if g["group"] == "GitHub-webhook")
        self.assertTrue(gh["complete"])
        self.assertIn("GITHUB_WEBHOOK_SECRET", gh["set"])
        self.assertIn("SENTRY_CLIENT_SECRET", gh["missing"])  # still reported as missing (by name)

    def test_langsmith_alias_counts_as_set(self):
        # LANGCHAIN_API_KEY is an accepted alias of LANGSMITH_API_KEY.
        report = _collect({"LANGGRAPH_DEPLOYMENT_URL": "u", "LANGCHAIN_API_KEY": _LS_KEY,
                           "LANGSMITH_TENANT_ID": "t"})
        ls = next(g for g in report["groups"] if g["group"] == "LangSmith")
        self.assertTrue(ls["complete"], "alias LANGCHAIN_API_KEY should satisfy LANGSMITH_API_KEY")


class WriteGateMisconfig(unittest.TestCase):
    def test_allowlist_set_but_floor_on_is_flagged(self):
        report = _collect({"AGENTS_WRITE_ENABLED": "cfo,ceo"})  # OPS_REPORT_ONLY unset ⇒ floor ON
        mis = report["write_gate"]["misconfig"]
        self.assertIsNotNone(mis)
        self.assertIn("OPS_REPORT_ONLY", mis)
        self.assertIn("stay report-only", mis.lower())
        # names of the affected agents are surfaced (config, not secret).
        self.assertEqual(report["write_gate"]["allowlisted_agents"], ["ceo", "cfo"])

    def test_floor_lifted_but_allowlist_empty_is_flagged(self):
        report = _collect({"OPS_REPORT_ONLY": "0"})  # floor lifted, allowlist empty
        mis = report["write_gate"]["misconfig"]
        self.assertIsNotNone(mis)
        self.assertIn("NOBODY", mis)

    def test_coordinated_config_is_clean(self):
        report = _collect({"OPS_REPORT_ONLY": "0", "AGENTS_WRITE_ENABLED": "cfo"})
        self.assertIsNone(report["write_gate"]["misconfig"])
        self.assertIn("cfo", report["write_gate"]["effective_write_enabled_pre_killswitch"])

    def test_safe_default_floor_on_empty_allowlist_is_clean(self):
        # The shipped default (floor ON, allowlist empty) is the SAFE state, not a misconfig.
        report = _collect({})
        self.assertIsNone(report["write_gate"]["misconfig"])
        self.assertTrue(report["write_gate"]["ops_report_only_floor_engaged"])

    def test_tier1_first_wave_is_surfaced(self):
        from agent_toolkit import write_gate as wg
        report = _collect({})
        self.assertEqual(set(report["write_gate"]["recommended_first_wave_TIER1"]),
                         set(wg.TIER1_WRITE_ENABLED))

    def test_named_but_never_listed_agent_is_surfaced(self):
        # email_triage is HARD never-listed — if named, it must show as named-but-blocked.
        report = _collect({"OPS_REPORT_ONLY": "0", "AGENTS_WRITE_ENABLED": "email_triage"})
        self.assertIn("email_triage", report["write_gate"]["never_listed_in_allowlist"])
        self.assertNotIn("email_triage",
                         report["write_gate"]["effective_write_enabled_pre_killswitch"])

    def test_floor_lifted_but_only_never_listed_named_is_flagged(self):
        # DEFECT (silent fail): floor LIFTED + AGENTS_WRITE_ENABLED names ONLY hard-never-listed
        # agents (e.g. email_triage) ⇒ the EFFECTIVE write set is EMPTY — the lift did NOTHING,
        # the exact "the lift did nothing" failure the preflight exists to catch. The allowlist is
        # syntactically non-empty, so the `(not allow) and (not floor_on)` branch misses it and the
        # gate is reported as coordinated. The misconfig MUST be flagged whenever the lift produces
        # no effective writer.
        report = _collect({"OPS_REPORT_ONLY": "0", "AGENTS_WRITE_ENABLED": "email_triage"})
        self.assertEqual(report["write_gate"]["effective_write_enabled_pre_killswitch"], [],
                         "precondition: no agent is effectively write-enabled")
        self.assertIsNotNone(
            report["write_gate"]["misconfig"],
            "floor lifted but NO agent effectively writes (allowlist all never-listed) must be a "
            "flagged misconfig, not reported as coordinated",
        )

    def test_exit_1_when_floor_lifted_but_no_effective_writer(self):
        # The exit-code policy must NOT green-light a deployment where the floor was lifted but the
        # allowlist names only never-listed agents (nobody graduates) — that is 'safe to activate'
        # reporting a no-op activation.
        env = {"LANGGRAPH_DEPLOYMENT_URL": "u", "LANGSMITH_API_KEY": _LS_KEY,
               "LANGSMITH_TENANT_ID": "t", "GITHUB_WEBHOOK_SECRET": _GH_VAL,
               "OPS_REPORT_ONLY": "0", "AGENTS_WRITE_ENABLED": "email_triage"}
        rc, out = _main_output([], env)
        self.assertEqual(rc, 1, "floor lifted with no effective writer must fail the preflight")


class ExitCodePolicy(unittest.TestCase):
    def test_exit_1_on_required_incomplete(self):
        rc, _ = _main_output([], {})  # nothing set
        self.assertEqual(rc, 1)

    def test_exit_1_on_write_gate_misconfig_even_if_required_complete(self):
        env = {"LANGGRAPH_DEPLOYMENT_URL": "u", "LANGSMITH_API_KEY": _LS_KEY,
               "LANGSMITH_TENANT_ID": "t", "GITHUB_WEBHOOK_SECRET": _GH_VAL,
               "AGENTS_WRITE_ENABLED": "cfo"}  # allowlist set but floor still on
        rc, _ = _main_output([], env)
        self.assertEqual(rc, 1)

    def test_exit_0_when_required_complete_and_gate_coordinated(self):
        env = {"LANGGRAPH_DEPLOYMENT_URL": "u", "LANGSMITH_API_KEY": _LS_KEY,
               "LANGSMITH_TENANT_ID": "t", "GITHUB_WEBHOOK_SECRET": _GH_VAL}
        rc, _ = _main_output([], env)
        self.assertEqual(rc, 0)

    def test_strict_fails_on_optional_incomplete(self):
        env = {"LANGGRAPH_DEPLOYMENT_URL": "u", "LANGSMITH_API_KEY": _LS_KEY,
               "LANGSMITH_TENANT_ID": "t", "GITHUB_WEBHOOK_SECRET": _GH_VAL}  # optional groups empty
        rc, _ = _main_output(["--strict"], env)
        self.assertEqual(rc, 1)

    def test_full_config_passes(self):
        rc, _ = _main_output(["--strict"], _FULL_ENV)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
