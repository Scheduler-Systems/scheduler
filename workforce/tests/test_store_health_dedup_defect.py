"""Regression: store_health_checker re-files a NEW issue every time severity changes.

THE DEFECT
----------
``graphs/ops/store_health_checker.deliver`` files its digest with a DYNAMIC title that bakes
the shift's severity into the title::

    file_digest_issue(DIGEST_REPO, "Store/RC health: " + severity, body,
                      agent="store_health_checker", ...)   # no record_kind=

and passes NO ``record_kind``. ``file_digest_issue`` therefore derives the recurring-record
kind from a slug of the title (``_title_kind``), so the dedup key embeds the severity:

    severity "ok"     -> record:store_health_checker:store-rc-health-ok
    severity "medium" -> record:store_health_checker:store-rc-health-medium
    severity "high"   -> record:store_health_checker:store-rc-health-high

Each is a DIFFERENT dedup key, so the hidden ``<!-- agent-record:{key} -->`` find-or-update
marker differs between shifts. The result: when the store flips ok -> high -> ok across
consecutive runs (exactly what a health checker does), the agent files a BRAND-NEW GitHub
issue every time the severity changes — the #33/#35/#43 duplicate-issue spam the whole dedup
mechanism exists to prevent, reintroduced through a non-stable title.

The dedup key must be STABLE per (agent, record_kind) — the SAME standing "store health"
record must be found-and-updated each shift regardless of the severity value. The fix is to
pass a stable ``record_kind`` (e.g. ``"store-health"``) so severity rides in the body, not the
dedup key.

This test injects a MOCKED GitHub client (no network, no real writes) and asserts ONE standing
issue across three shifts. It FAILS today (three issues are filed) and will PASS once
``deliver`` passes a stable ``record_kind``.

Run: ../../.venv/bin/python -m unittest tests.test_store_health_dedup_defect -v
"""
import unittest
from unittest import mock

from agent_toolkit import github_ops as go
from agent_toolkit import ops_report

# Reuse the growing-client + mock-issue plumbing from the exec-digest / records tests
# (an issue created on shift 1 is visible to shift 2's find-or-update).
from tests.test_github_records import _make_issue


REPO = "Scheduler-Systems/qa-agent-platform"


def _make_growing_client(store):
    """A mock Github client whose repo's OPEN issues are ``store`` and whose ``create_issue``
    APPENDS to ``store`` (fleet-bot author + composed marker-carrying body + labels), so an
    issue filed on an earlier shift is visible to a later shift's find-or-update."""
    repo = mock.Mock()
    repo.get_issues.side_effect = lambda state="open": list(store)

    def _create_issue(title, body, labels):
        iss = _make_issue(number=len(store) + 100, body=body,
                          labels=list(labels or []), author="fleet[bot]")
        store.append(iss)
        return iss
    repo.create_issue.side_effect = _create_issue
    client = mock.Mock()
    client.get_repo.return_value = repo
    return client, repo


def _file_store_health(severity, body):
    """Drive the REAL ``store_health_checker.deliver`` node for one shift at ``severity``.

    This exercises the production delivery call path end-to-end (not a re-implementation of it),
    so the test passes ONLY when ``deliver`` actually passes a stable ``record_kind``. The state
    carries the severity + a digest body; ``deliver`` renders, writes the local artifact, and
    files the deduped GitHub record via the seam under report-only.
    """
    from graphs.ops import store_health_checker as shc

    state = {
        "severity": severity,
        "summary": body,
        "sku_findings": [],
        "paywall": [],
    }
    # Force report-only regardless of the ambient env so the record writes without a gate.
    with mock.patch.object(shc, "_report_only", return_value=True):
        shc.deliver(state)
    # Return value not needed by the dedup assertion (we inspect the issue store); but the
    # per-shift dedup status the test checks is derived from the store growth below.
    return None


class StoreHealthDedupStableAcrossSeverityChanges(unittest.TestCase):
    """A standing store-health record must be ONE issue, found-and-updated each shift —
    regardless of whether the shift's severity is ok / medium / high."""

    def test_severity_change_does_not_spawn_a_new_issue(self):
        issues = []
        client, repo = _make_growing_client(issues)
        ops = go.GitHubOps(report_only=True, gh_client=client)

        with mock.patch("agent_toolkit.github_ops.GitHubOps", return_value=ops), \
             mock.patch("agent_toolkit.slack_tool.post_digest", return_value={"status": "posted"}):
            # Three consecutive shifts of the SAME standing check, severity flipping as the
            # store degrades and recovers — the normal life of a health checker.
            _file_store_health("ok",     "shift 1: store + paywall healthy")
            self.assertEqual(len(issues), 1, "shift 1 should create the standing record")
            _file_store_health("high",   "shift 2: SKU non-purchasable — revenue at risk")
            self.assertEqual(len(issues), 1,
                             "shift 2 (severity change) should UPDATE the standing record, not re-file")
            _file_store_health("ok",     "shift 3: store recovered")

        self.assertEqual(
            len(issues), 1,
            f"store_health_checker filed {len(issues)} issues across 3 shifts; expected 1 "
            "standing record. If severity is baked into the dedup key, every ok->high->ok flip "
            "re-files a duplicate issue (the #33/#35/#43 spam). The fix is a STABLE record_kind "
            "(e.g. 'store-health') so severity rides in the body, not the dedup key.",
        )
        # The single standing issue accumulates the per-shift updates as comments (shifts 2 & 3).
        self.assertEqual(len(issues[0]._comments), 2,
                         "the two later shifts should each append one update comment")


if __name__ == "__main__":
    unittest.main()
