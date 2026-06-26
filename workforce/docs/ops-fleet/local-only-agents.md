# Local-only agents (NOT deployed graphs, NOT roster employees)

Two ops agents are **local-only launchd workers**, not deployed LangSmith graphs:

| Agent | Code | Original schedule | Status |
|---|---|---|---|
| `git_sync_auditor` (Sage) | `graphs/ops/git_sync_auditor.py` | hourly (local launchd) — report-only | local-only; dead under macOS TCC |
| `memory_sync` (Remy)      | `graphs/ops/memory_sync.py`      | every 30 min (local launchd) — dry-run | local-only; dead under macOS TCC |

## Why they are NOT on the deployed-workforce roster

`roster.yaml` is the HR record of the **deployed** agent workforce — it is kept 1:1 with the
graphs in `langgraph.json` (enforced by `scripts/check_roster_coverage.py`: every deployed graph
has exactly one employee row). These two agents:

- are **not registered in `langgraph.json`** (they were never deployed to the LangSmith runtime);
- have **no capability grant** in `docs/governance/capabilities.yaml`;
- ran on the Mac via `launchd` and are **dead under macOS TCC** (Full Disk Access / Touch ID; see
  the workspace memory note "QA fleet triggers broken").

Listing them as `agents:` rows (with a salary, scorecard, `status: probation`) made them look like
deployed employees that were merely idle — a **"ghost employee"**: a rostered name with no deployed
graph. The HR coverage gate could not catch this (it only checks *deployed → rostered*, not
*rostered → deployed*), so the confusion was silent and a future re-deploy could have landed against
the wrong record.

## The reconciliation (2026-06-07, ops-fleet-prod-harden)

- **Removed** `git_sync_auditor` and `memory_sync` from `roster.yaml` — both the `agents:` employee
  records **and** the `org.ops` routing list.
- Consequence in `agent_toolkit/collaboration.py`: `OrgChart.dept_of("git_sync_auditor")` and
  `dept_of("memory_sync")` now return `None`; they can never be offered as a delegation target
  (the `deployed`-graph filter is the second line of defense).
- Consequence in `graphs/ops/daily_digest.py`: excluded from the `ROLE_CLASS` ops fallback so the
  autonomy scoreboard never counts a ghost as staffed. Their **local digests** are still stitched
  into the daily digest via `OPS_DIGESTS` (`git-sync-auditor` / `memory-sync` local artifacts) —
  fail-safe file reads when the artifact exists.

## If you ever promote one to a deployed graph

Do **not** simply re-add a roster row. Onboard it through HR like any new agent:

1. register the graph in `langgraph.json`;
2. add an agent-only, spend-only, `report_only` grant in `docs/governance/capabilities.yaml`;
3. add an `agents:` employee row (role, grade, schedule, salary, `status: probation`,
   `hire: pending_hr_approval`) in `roster.yaml` and its `org:` department;
4. let `scripts/check_roster_coverage.py` + `scripts/check_capability_coverage.py` pass.
