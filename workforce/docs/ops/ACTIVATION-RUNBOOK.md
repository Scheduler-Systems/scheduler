# Activation runbook — agent company (for the next orchestrator)

**State:** fully built, tested, committed, pushed on `feat/ops-fleet` (PR #37, base
`phase-0-foundation`). **Everything is report-only / probation. Nothing is activated.** 23
rostered agents (board 3 · exec 5 · growth 3 · qa 7 · ops 5); 26 cloud graphs in
`langgraph.json`; 379 unit tests green. Fleet runs only when triggered manually today.

## ✅ BLOCKER RESOLVED — deploy key in `.env` (updated 2026-06-05)
The `LANGSMITH_API_KEY` in the main repo `.env` and `worktrees/qa-deploy/.env` is now a
**service key with Deploy scope** (`lsv2_sk_...`).  The worktree `.env` for `ops-fleet` stays
secret-free (only `OPS_REPORT_ONLY=1`) — secrets are passed via `export` at deploy time.

### Deploy steps (managed)
Both deployments are **CLI-created** (LangSmith UI "New Revision" is disabled — confirmed by its
tooltip), region **EU (europe-west4)**:
- `scheduler-qa-agents`  → deployment id `88bf7aa7-d67e-4ff8-b3e7-7f2e659088be`
- `scheduler-qa-fleet`   → deployment id `ddff3309-6ac6-4fc7-883b-0ae228a562d4`

```bash
cd .../qa-agent-platform/worktrees/ops-fleet

# 1. Export deploy-scoped key from main .env (NEVER commit to ops-fleet/.env)
export LANGSMITH_API_KEY=$(grep LANGSMITH_API_KEY ../../.env | cut -d= -f2-)
export LANGGRAPH_API_KEY="$LANGSMITH_API_KEY"

# 2. Deploy both deployments
./.venv/bin/langgraph deploy --deployment-id 88bf7aa7-d67e-4ff8-b3e7-7f2e659088be --no-input
./.venv/bin/langgraph deploy --deployment-id ddff3309-6ac6-4fc7-883b-0ae228a562d4 --no-input

# 3. Verify health
curl -s -o /dev/null -w '%{http_code}\n' -H "x-api-key: $LANGSMITH_API_KEY" \
  https://scheduler-qa-agents-49190f122ed15fa18b25b973d714a94d.eu.langgraph.app/ok   # expect 200

# 4. Smoke: trigger daily_digest via LangSmith UI or API
```

### Runtime secrets — set in LangSmith deployment settings UI
The worktree `.env` intentionally carries NO secrets.  Add the following in the LangSmith UI
under each deployment → "Environment secrets":

| Variable | Value / Source |
|---|---|
| `ANTHROPIC_API_KEY` | from main `.env` |
| `GEMINI_API_KEY` | from main `.env` |
| `GOOGLE_API_KEY` | from main `.env` |
| `GITHUB_APP_PRIVATE_KEY` | from main `.env` |
| `GITHUB_APP_ID` | from main `.env` |
| `GITHUB_APP_INSTALLATION_ID` | from main `.env` |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | SA key JSON from `projects/priority-118da/secrets/claude-automation-sa-key` — see below |
| `DEEPSEEK_API_KEY` | from main `.env` (if using DeepSeek) |

### GCP / Firebase credentials — no interactive auth needed
`agent_toolkit/gcp_auth.py` bootstraps `GOOGLE_APPLICATION_CREDENTIALS` automatically at
import time (called from `agent_toolkit/__init__.py`) using this priority chain:

1. `GOOGLE_APPLICATION_CREDENTIALS` already set → **no-op**
2. `GOOGLE_APPLICATION_CREDENTIALS_JSON` env var → write JSON to temp file and export creds
   *(Set this in LangSmith deployment secrets — paste the full SA key JSON)*
3. `~/.config/gcp-claude/activate.sh` exists → source it *(dev machines)*
4. Secret Manager REST API via ADC → fetch `projects/priority-118da/secrets/claude-automation-sa-key`
   *(works when the LangSmith runtime SA has `secretmanager.versions.access`)*

To get the JSON value for `GOOGLE_APPLICATION_CREDENTIALS_JSON`:
```bash
gcloud secrets versions access latest \
  --secret=claude-automation-sa-key --project=priority-118da
```
Paste the full JSON output as the env secret value in LangSmith.

### scheduler-api CI/CD (already correct — no changes needed)
The `deploy-functions.yml` workflow uses **Workload Identity Federation** via
`google-github-actions/auth@v3` with `GCP_WORKLOAD_IDENTITY_PROVIDER` and
`GCP_SERVICE_ACCOUNT` repository secrets.  This is the correct approach for CI/CD — no
service account key files, no hardcoded credentials.

After deploy, in-cluster/platform **Crons** drive the cadences (daily digest 09:30,
store-health 08:30, weekly revenue/conversion).

## Local agents + Mac offload (state)
`git_sync_auditor` + `memory_sync` are **purpose-bound to this Mac** (they observe its local
git/memory) — they can't lift-and-shift. Real offload = git→GitHub-source-of-truth +
memory→Litestream-to-GCS + cloud agents→in-cluster. **Next wave (designed, not built):**
`docs/ops/mac-offload-plan.md` — argocdgitops Application + Vault least-privilege secrets + GitHub-
clone workspace, via the **devops-engineer** specialist. **Converge** with the concurrent sync
session's launchd daemons (`git-remote-sync`, `memory-langgraph-sync`, `agentmode-sync` — all
TCC-blocked, `runs=0`): roster agents are canonical; coordinate before removing either side's jobs.
NOTE: local launchd is **TCC-blocked** (can't read `~/Documents`) — do NOT rely on it; use cluster.

## Kill switch (human override — Shay has it at all times)
```bash
./.venv/bin/python scripts/fleet_control.py status        # show state
./.venv/bin/python scripts/fleet_control.py kill-all       # FLEET STOP (.payroll/FLEET_DISABLED)
./.venv/bin/python scripts/fleet_control.py revive-all
./.venv/bin/python scripts/fleet_control.py bench <agent>  # stop ONE (.payroll/benched.json)
```
Also env: `AGENTS_DISABLED=1` (fleet), `AGENTS_BENCHED="a,b"` (agents). Wired into
`check_clocked_in` (checked first, fail-safe). Full contract: `docs/ops/safety-model.md` (incl.
"investor away" mode: gated items QUEUE, never block; only capital/irreversible/legal escalate).

## Hard limits (founder-set)

Token caps and fleet constraints are **founder-set**. The CFO agent may recommend changes but **cannot apply them**. Any change to `per_run_token_ceiling`, `team_token_budget`, or agent salary requires Shay's explicit sign-off.

See `qa-agent-platform/.env` for the env-var form of these limits (`AGENT_PER_RUN_TOKEN_CAP`, `AGENT_TEAM_WEEKLY_TOKEN_CAP`).

## Wave activation plan + CFO budget report
- **Wave 1 (done, ran manually):** QA shift (105 e2e tests on `qa/e2e-schedule-creation-20260605`
  branches across scheduler-{web,ios,android,api}; test-only, no merges) + growth/revenue agents.
- **CFO budget report:** the `cfo` graph **is built**; running it writes `.tmp/cfo/latest.md` = a
  budget-allocation proposal across the roster that keeps total ≤ `team_token_budget` (5.54M),
  benches un-scheduled agents at ~0, escalates increases to Shay. **This is the gate for mass
  hiring** — the full 81-role roster is deliberately NOT registered yet (containment + frugality).
- **Next waves:** ops → departments by ROI, each gated on **scorecards + CFO budget sign-off**.
  Keep waves small (a misbehaving wave must stay contained). Default cheapest grade that passes.
- **Run the fleet manually any time** (report-only, no creds needed):
  `OPS_REPORT_ONLY=1 ./.venv/bin/python scripts/run_ops_graph.py <graph>` (resolves ops/marketing/
  exec/board); local agents via `scripts/run_git_sync_auditor.sh` / `run_memory_sync.sh`; QA shift
  via `scripts/run_qa_shift` workflow or `scripts/run_qa_assignment.py`.

## Scheduler org-view (handed off)
Do NOT build it here. Spec for the dedicated product session:
`docs/product/agent-workforce-requirements.md` (schedules ≠ org chart; roster.yaml = system of
record; agent metadata grade/salary/status/scorecard/shift; IDOR-identity constraint).

## Key paths
roster.yaml · langgraph.json · agent_toolkit/{budget,payroll,ops_report,revenuecat,http_probe}.py
· graphs/{ops,marketing,exec,board}/ · scripts/{fleet_control,run_ops_graph,run_qa_assignment}.py
· docs/ops/{safety-model,mac-offload-plan,ops-fleet}.md · docs/product/agent-workforce-requirements.md
