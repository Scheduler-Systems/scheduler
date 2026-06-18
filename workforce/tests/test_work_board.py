"""Tests for the work board (issue selection + staleness). stdlib unittest, no network.

Run: .venv/bin/python -m unittest tests.test_work_board -v
"""
import unittest
from datetime import datetime, timezone

from agent_toolkit import work_board as wb

NOW = datetime(2026, 6, 4, tzinfo=timezone.utc)


def item(repo, number=1, updated="2026-06-01T00:00:00Z", labels=()):
    return wb.WorkItem(repo=repo, number=number, title="t", updated_at=updated, labels=tuple(labels))


class StalenessTests(unittest.TestCase):
    def test_fresh(self):
        v = wb.classify_staleness(item("Scheduler-Systems/scheduler-web"), NOW)
        self.assertFalse(v.stale)

    def test_idle_too_long(self):
        v = wb.classify_staleness(item("x/y", updated="2026-01-01T00:00:00Z"), NOW)
        self.assertTrue(v.stale)
        self.assertIn("idle", v.reason)

    def test_stale_label_overrides_recent_update(self):
        v = wb.classify_staleness(
            item("x/y", updated="2026-06-03T00:00:00Z", labels=["Stale"]), NOW
        )
        self.assertTrue(v.stale)
        self.assertIn("stale", v.reason)

    def test_blocked_label(self):
        v = wb.classify_staleness(item("x/y", labels=["blocked"]), NOW)
        self.assertTrue(v.stale)

    def test_missing_timestamp_is_stale(self):
        v = wb.classify_staleness(item("x/y", updated=""), NOW)
        self.assertTrue(v.stale)

    def test_custom_threshold(self):
        it = item("x/y", updated="2026-05-30T00:00:00Z")  # 5 days old
        self.assertFalse(wb.classify_staleness(it, NOW, max_idle_days=30).stale)
        self.assertTrue(wb.classify_staleness(it, NOW, max_idle_days=3).stale)


class AssignTests(unittest.TestCase):
    def test_known_repos(self):
        self.assertEqual(wb.assign_role(item("Scheduler-Systems/scheduler-web")), "web_automation_engineer")
        self.assertEqual(wb.assign_role(item("Scheduler-Systems/scheduler-ios")), "ios_automation_engineer")

    def test_unknown_repo_unassigned(self):
        self.assertIsNone(wb.assign_role(item("Scheduler-Systems/legal")))


class SelectWorkTests(unittest.TestCase):
    def test_routes_fresh_allowed_to_role(self):
        sel = wb.select_work([item("Scheduler-Systems/scheduler-web", number=7)], NOW)
        self.assertIn("web_automation_engineer", sel.by_role)
        self.assertEqual(sel.by_role["web_automation_engineer"][0].number, 7)

    def test_drops_stale(self):
        sel = wb.select_work([item("Scheduler-Systems/scheduler-web", updated="2026-01-01T00:00:00Z")], NOW)
        self.assertEqual(sel.by_role, {})
        self.assertEqual(len(sel.stale), 1)

    def test_skips_non_allowlisted_repo(self):
        # legal is NOT in github_ops.ALLOWED_REPOS -> invisible by construction
        sel = wb.select_work([item("Scheduler-Systems/legal", number=174)], NOW)
        self.assertEqual(sel.by_role, {})
        self.assertEqual(len(sel.skipped_not_allowed), 1)

    def test_allowed_but_unassigned_repo_surfaced(self):
        # scheduler-api is allow-listed but has no role mapping yet -> unassigned (honest signal)
        self.assertIn("Scheduler-Systems/scheduler-api", wb.ALLOWED_REPOS)
        sel = wb.select_work([item("Scheduler-Systems/scheduler-api")], NOW)
        self.assertEqual(len(sel.unassigned), 1)
        self.assertEqual(sel.by_role, {})


if __name__ == "__main__":
    unittest.main()
