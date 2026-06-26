"""Tests for the server-side cron-setup (replaces the dead launchd cron).

All MOCKED — a fake SDK client records crons.create/search calls; no real network. We assert:
  * DRY-RUN BY DEFAULT: ``run(apply=False)`` calls NO mutating method (only search) and creates
    nothing — creating crons is the gated activation, so the default must be side-effect-free.
  * ``--apply`` creates exactly the missing crons.
  * IDEMPOTENT: with the crons already present on the server, ``--apply`` creates nothing; a
    second apply run is a no-op.
  * the CLI defaults to dry-run (``main([])`` creates nothing) and refuses to apply without
    confirmation.
  * every scheduled cron targets a real graph and only scheduled (not event-driven) agents.
"""
from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest import mock

from scripts import setup_crons as sc


class _FakeCrons:
    def __init__(self, existing):
        self._existing = list(existing)
        self.created: list[dict] = []
        self.search_calls = 0

    async def search(self, *, limit=100, offset=0, **kw):
        self.search_calls += 1
        if offset >= len(self._existing):
            return []
        return self._existing[offset:offset + limit]

    async def create(self, assistant_id, *, schedule, input=None, metadata=None, **kw):
        rec = {"assistant_id": assistant_id, "schedule": schedule, "input": input,
               "cron_id": f"cron-{len(self.created)}"}
        self.created.append(rec)
        # a created cron becomes "existing" so a follow-up search sees it (idempotency realism)
        self._existing.append({"assistant_id": assistant_id, "schedule": schedule})
        return rec


class _FakeClient:
    def __init__(self, existing=None):
        self.crons = _FakeCrons(existing or [])


def _run(coro):
    return asyncio.run(coro)


class DryRunDefault(unittest.TestCase):
    def test_dry_run_creates_nothing(self):
        client = _FakeClient(existing=[])
        plan = _run(sc.run(sc.DEFAULT_CRONS, apply=False, client=client))
        self.assertFalse(plan["apply"])
        self.assertEqual(client.crons.created, [])           # NOTHING created
        self.assertEqual(plan["created"], [])
        # it still computed what it WOULD create (all of them, server is empty)
        self.assertEqual(len(plan["to_create"]), len(sc.DEFAULT_CRONS))

    def test_dry_run_only_calls_search_never_create(self):
        client = _FakeClient(existing=[])
        with mock.patch.object(client.crons, "create",
                               side_effect=AssertionError("create must NOT be called in dry-run")):
            _run(sc.run(sc.DEFAULT_CRONS, apply=False, client=client))
        self.assertGreaterEqual(client.crons.search_calls, 1)


class Apply(unittest.TestCase):
    def test_apply_creates_missing_crons(self):
        client = _FakeClient(existing=[])
        plan = _run(sc.run(sc.DEFAULT_CRONS, apply=True, client=client))
        self.assertTrue(plan["apply"])
        created_assistants = {c["assistant_id"] for c in client.crons.created}
        self.assertEqual(created_assistants, {s.assistant for s in sc.DEFAULT_CRONS})
        self.assertEqual(len(plan["created"]), len(sc.DEFAULT_CRONS))

    def test_apply_is_idempotent(self):
        # pre-seed the server with all the crons already registered
        existing = [{"assistant_id": s.assistant, "schedule": s.schedule} for s in sc.DEFAULT_CRONS]
        client = _FakeClient(existing=existing)
        plan = _run(sc.run(sc.DEFAULT_CRONS, apply=True, client=client))
        self.assertEqual(client.crons.created, [])           # nothing new
        self.assertEqual(plan["to_create"], [])
        self.assertEqual(len(plan["already_present"]), len(sc.DEFAULT_CRONS))

    def test_double_apply_no_duplicates(self):
        client = _FakeClient(existing=[])
        _run(sc.run(sc.DEFAULT_CRONS, apply=True, client=client))
        first = len(client.crons.created)
        _run(sc.run(sc.DEFAULT_CRONS, apply=True, client=client))  # again, same client/state
        self.assertEqual(len(client.crons.created), first)   # no growth -> no duplicates

    def test_partial_existing_only_creates_the_gap(self):
        # server already has daily_digest; the rest are missing
        existing = [{"assistant_id": "daily_digest", "schedule": "0 8 * * *"}]
        client = _FakeClient(existing=existing)
        plan = _run(sc.run(sc.DEFAULT_CRONS, apply=True, client=client))
        created = {c["assistant_id"] for c in client.crons.created}
        self.assertNotIn("daily_digest", created)
        self.assertEqual(created, {s.assistant for s in sc.DEFAULT_CRONS} - {"daily_digest"})


class DiffNormalization(unittest.TestCase):
    def test_whitespace_insensitive_match(self):
        existing = [{"assistant_id": "daily_digest", "schedule": "0   8 * * *"}]  # extra spaces
        to_create, already = sc.diff_crons(
            [sc.CronSpec("daily_digest", "0 8 * * *", "d")], existing)
        self.assertEqual(to_create, [])
        self.assertEqual(len(already), 1)

    def test_different_schedule_is_a_create(self):
        existing = [{"assistant_id": "daily_digest", "schedule": "0 9 * * *"}]  # different time
        to_create, already = sc.diff_crons(
            [sc.CronSpec("daily_digest", "0 8 * * *", "d")], existing)
        self.assertEqual(len(to_create), 1)
        self.assertEqual(already, [])


class CliDefaults(unittest.TestCase):
    def test_main_defaults_to_dry_run_and_creates_nothing(self):
        client = _FakeClient(existing=[])
        with mock.patch.object(sc, "_build_client", return_value=client):
            rc = sc.main([])  # no --apply
        self.assertEqual(rc, 0)
        self.assertEqual(client.crons.created, [])

    def test_main_apply_without_yes_aborts_on_no_confirm(self):
        client = _FakeClient(existing=[])
        with mock.patch.object(sc, "_build_client", return_value=client), \
             mock.patch("builtins.input", return_value="n"):
            rc = sc.main(["--apply"])
        self.assertEqual(rc, 1)                               # aborted
        self.assertEqual(client.crons.created, [])            # created nothing

    def test_main_apply_with_yes_creates(self):
        client = _FakeClient(existing=[])
        with mock.patch.object(sc, "_build_client", return_value=client):
            rc = sc.main(["--apply", "--yes"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(client.crons.created), len(sc.DEFAULT_CRONS))


class CronSanity(unittest.TestCase):
    def test_all_crons_target_real_graphs(self):
        with open(os.path.join(sc._REPO_ROOT, "langgraph.json")) as fh:
            cfg = json.load(fh)
        graphs = set(cfg["graphs"])
        for spec in sc.DEFAULT_CRONS:
            self.assertIn(spec.assistant, graphs, f"{spec.assistant} not a deployed graph")

    def test_no_event_driven_qa_agents_in_cron_list(self):
        # QA is event-driven, not scheduled — the QA workers must NOT be cron'd here.
        qa_event_agents = {"qa_lead_aggregator", "web_qa_regression", "web_automation_engineer",
                           "android_automation_engineer", "ios_automation_engineer"}
        cron_agents = {s.assistant for s in sc.DEFAULT_CRONS}
        self.assertEqual(cron_agents & qa_event_agents, set())

    def test_schedules_are_five_field_cron(self):
        for spec in sc.DEFAULT_CRONS:
            self.assertEqual(len(spec.schedule.split()), 5, f"bad cron: {spec.schedule}")


# =============================================================================================
# FINDING 4 — the cron set is DERIVED from roster.yaml at runtime (no static list).
# =============================================================================================
class DeriveFromRoster(unittest.TestCase):
    """``derive_crons_from_roster`` picks up scheduled rostered agents automatically, excludes the
    event-driven QA group + local-only agents, and maps cadences to UTC times."""

    GRAPHS = {"daily_digest", "store_health_checker", "revenue_reporter", "ceo",
              "web_manual_tester", "web_automation_engineer", "new_officer", "weekly_thing",
              "event_thing", "local_only_thing"}

    def _roster(self):
        return {
            "org": {"qa": ["web_manual_tester", "web_automation_engineer"]},
            "agents": {
                "daily_digest": {"role": "digest", "schedule": "daily (08:00) — once a day"},
                "store_health_checker": {"role": "store guard", "schedule": "daily (08:30) — report-only"},
                "revenue_reporter": {"role": "rc metrics", "schedule": "weekly (Mon 09:00) — report-only"},
                "ceo": {"role": "ceo", "schedule": "daily — propose-only"},
                # QA group → excluded even though it says "daily"
                "web_manual_tester": {"role": "qa", "schedule": "daily"},
                # QA group, event-driven → excluded
                "web_automation_engineer": {"role": "qa", "schedule": "on every PR -> scheduler-web"},
                # a NEW scheduled officer not in any static list → must auto-register
                "new_officer": {"role": "new CISO digest", "schedule": "daily + on alert — propose-only"},
                # a new WEEKLY agent → weekly cron
                "weekly_thing": {"role": "weekly job", "schedule": "weekly — report-only"},
                # purely event-driven (no daily/weekly token) → excluded
                "event_thing": {"role": "evt", "schedule": "event-driven (PR/push) — report-only"},
                # local-only: deployed graph name present here BUT we drop it from GRAPHS in one test
                "local_only_thing": {"role": "local", "schedule": "daily (local launchd)"},
                # an undeployed scheduled agent (not in GRAPHS) → excluded (no assistant)
                "ghost_scheduled": {"role": "ghost", "schedule": "daily"},
            },
        }

    def _derived(self, graphs=None):
        return sc.derive_crons_from_roster(self._roster(), graphs if graphs is not None else self.GRAPHS)

    def test_daily_scheduled_agent_is_in_the_plan(self):
        names = {s.assistant for s in self._derived()}
        self.assertIn("store_health_checker", names)   # the AC: a daily agent appears
        self.assertIn("daily_digest", names)
        self.assertIn("ceo", names)

    def test_event_driven_qa_agent_is_not_in_the_plan(self):
        names = {s.assistant for s in self._derived()}
        # the AC: an event-driven QA agent does NOT appear
        self.assertNotIn("web_automation_engineer", names)
        # a QA-group agent is excluded even when its line says "daily"
        self.assertNotIn("web_manual_tester", names)

    def test_purely_event_driven_non_qa_agent_excluded(self):
        names = {s.assistant for s in self._derived()}
        self.assertNotIn("event_thing", names)

    def test_new_scheduled_officer_auto_registers(self):
        # The whole point: a future scheduled officer with no static entry is picked up.
        spec = next((s for s in self._derived() if s.assistant == "new_officer"), None)
        self.assertIsNotNone(spec, "a new daily-scheduled officer must auto-register")
        self.assertEqual(spec.input["cadence"], "daily")
        self.assertEqual(len(spec.schedule.split()), 5)

    def test_weekly_agent_maps_to_monday_cron(self):
        spec = next(s for s in self._derived() if s.assistant == "weekly_thing")
        self.assertEqual(spec.schedule.split()[-1], "1")  # day-of-week = Monday
        self.assertEqual(spec.input["cadence"], "weekly")

    def test_known_explicit_times_are_honored(self):
        by = {s.assistant: s.schedule for s in self._derived()}
        self.assertEqual(by["daily_digest"], "0 8 * * *")       # 08:00
        self.assertEqual(by["store_health_checker"], "30 8 * * *")  # 08:30 (parsed/known)
        self.assertEqual(by["revenue_reporter"], "0 9 * * 1")   # Mon 09:00

    def test_undeployed_agent_excluded(self):
        names = {s.assistant for s in self._derived()}
        self.assertNotIn("ghost_scheduled", names)  # not in GRAPHS ⇒ no assistant to cron

    def test_local_only_agent_excluded_when_not_a_graph(self):
        # If the local-only agent is NOT a deployed graph, it must be excluded.
        derived = self._derived(graphs=self.GRAPHS - {"local_only_thing"})
        self.assertNotIn("local_only_thing", {s.assistant for s in derived})

    def test_derivation_is_deterministic_and_sorted(self):
        a = [s.assistant for s in self._derived()]
        b = [s.assistant for s in self._derived()]
        self.assertEqual(a, b)
        self.assertEqual(a, sorted(a))

    def test_staggered_slot_is_stable_hash_not_salted_builtin(self):
        # IDEMPOTENCY DEPENDS ON THIS: the un-timed slot must use a STABLE hash (sha256), not the
        # PYTHONHASHSEED-salted builtin hash() — else a re-run would mint duplicate crons at new
        # times. Recompute a slot for the same name many times; it must never change, and it must
        # match a fresh sha256-based computation (proving it isn't the salted builtin).
        import hashlib
        for name in ("new_officer", "some_future_agent", "another_one"):
            slots = {sc._slot_for(name) for _ in range(50)}
            self.assertEqual(len(slots), 1, f"{name}: _slot_for is not stable within a process")
            h = int(hashlib.sha256(name.encode("utf-8")).hexdigest(), 16)
            self.assertEqual(sc._slot_for(name), (8 + ((h // 12) % 2), (h % 12) * 5),
                             f"{name}: slot is not the documented stable-sha256 mapping")

    def test_unknown_daily_agent_gets_valid_window_slot(self):
        spec = next(s for s in self._derived() if s.assistant == "new_officer")
        minute, hour = spec.schedule.split()[0], spec.schedule.split()[1]
        self.assertIn(int(hour), (8, 9))
        self.assertIn(int(minute), range(0, 56, 5))

    def test_live_roster_derivation_excludes_all_qa_group(self):
        # Against the REAL roster + langgraph.json: no org.qa member is ever cron'd.
        import yaml
        roster = yaml.safe_load(open(os.path.join(sc._REPO_ROOT, "roster.yaml")).read())
        graphs = set(json.load(open(os.path.join(sc._REPO_ROOT, "langgraph.json")))["graphs"])
        qa_group = set((roster.get("org") or {}).get("qa") or [])
        names = {s.assistant for s in sc.derive_crons_from_roster(roster, graphs)}
        self.assertEqual(names & qa_group, set(), f"QA group leaked into crons: {names & qa_group}")
        # and a known daily ops agent IS present.
        self.assertIn("store_health_checker", names)


if __name__ == "__main__":
    unittest.main()
