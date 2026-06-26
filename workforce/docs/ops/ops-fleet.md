# Company agent fleet — production roles on LangGraph (revenue-first)

Staffs recurring company processes as LangGraph agents on the qa-agent-platform, registered
in `roster.yaml` as employees (salary = token budget, shift = schedule, grade = model tier,
scorecard). Ordered **revenue-first**: GROWTH leads (the revenue generators), then QA
(quality enablement — QA makes the product good, it does not itself generate revenue), then
OPS (keep-the-lights-on). **All start `status: probation`, report-only / propose-only** — no
mutating or outward action without a human gate (the `hr_ops_manager` model). Tracing goes to
the same LangSmith project as the rest of the fleet.

Goal this serves (Shay): *the whole company operational 24/7, observed once a day.* The
`daily_digest` makes progress toward that measurable day over day via an autonomy scoreboard.

## Architecture Decisions (frozen 2026-06-05)

These decisions are locked — do not change without Shay's explicit sign-off.

| Decision | Rule |
|---|---|
| **Workforce layer** | `scheduler-web` / `scheduler-api` own agent profiles + shift schedules. All scheduling goes through Scheduler — not cron, not LangSmith triggers directly. |
| **Runtime layer** | Agents are deployed on LangSmith (EU: `scheduler-qa-agents`, `scheduler-qa-fleet`). Scheduler triggers LangSmith endpoints at shift start. Future runtimes slot in the same way. |
| **QA trigger model** | QA agents fire on GitHub webhooks (PR open/merge/push), deploy hooks, and Sentry alerts — **not** cron schedules. |
| **Budget authority** | CFO agent monitors and reports only. Hard spending limits are **founder-set only** — any threshold change requires Shay's explicit approval. |
| **Escalation policy** | Only financial/capital/legal decisions escalate to Shay. All other operational, engineering, and product decisions are resolved autonomously by the executive agent team. |

## Roster (revenue-first)

### 💰 GROWTH — revenue generators (propose-only drafts; human gates anything live)
| Agent | Class | Schedule (staged) | Mission | Output |
|---|---|---|---|---|
| `conversion_growth_analyst` | CLOUD | weekly (+ funnel change) | Watches the RC funnel (252 cust / 1 paid / $5 MRR ≈ 0.4%), paywall, trials → proposes concrete conversion **experiments** | report-only GitHub draft + local digest |
| `aso_store_listing_agent` | CLOUD | monthly / on demand | Store-listing **repositioning** research + ASO copy drafts (reposition the mispositioned "to-do" listing → B2B shift scheduling; no app release) | draft, with a **no-over-claim** compliance scan |
| `content_campaign_drafter` | CLOUD | on demand | Email / social / blog **drafts** for review — never sends | draft + compliance scan |

### 🧪 QA — quality enablement (not revenue)
The existing 6+1 engineers/testers (`qa_lead_aggregator`, web/android/ios automation + manual)
are activation-ready. **First assignment = close the zero-e2e gap** on the unmerged
schedule-creation branches (`docs/qa/first_assignment.json`), which unblocks shipping:
`scheduler-web fix/web-newschedule-i18n`, `scheduler-ios fix/ios-schedule-creation`,
`scheduler-android fix/android-schedule-creation`, `scheduler-api fix/schedule-name-canonical-semantics`.
Run report-only via `scripts/run_qa_assignment.py` (real e2e dispatch only under
`QA_ASSIGNMENT_DISPATCH=1`, attended). **Open role flagged:** `scheduler-api` has no automation
engineer — a hire for `hr_ops_manager` to propose.

### 🛠️ OPS — keep-the-lights-on
| Agent | Class | Schedule (staged) | Mission | Output |
|---|---|---|---|---|
| `git_sync_auditor` | LOCAL (launchd) | hourly | Read-only local↔remote git divergence across the workspace; recency/unpushed guard built in | local digest |
| `memory_sync` | LOCAL (launchd) | every 30 min | Sync local memory stores → remote via a pluggable backend (dry-run) | local digest; uploads **nothing** |
| `revenue_reporter` | CLOUD | weekly (Mon 09:00) | RC metrics + deploy state + pipeline digest | local digest + report-only GitHub draft |
| `store_health_checker` | CLOUD | daily (08:30) | Non-purchasable SKUs, offering/trial drift, paywall reachability (revenue guard) | local digest + report-only alert draft |
| `daily_digest` | CLOUD (+ local) | daily (08:00) | **The once-a-day single pane** (below) | local digest + report-only GitHub draft |

## The daily digest — observe once a day
`daily_digest` is the one place to look. It **leads with an autonomy scoreboard** that answers
"when is the whole company operational 24/7?", then revenue → quality → ops → workforce:
- **STAFFED N / ~81** (roster vs. the full `docs/audit/processes.json` workforce target).
- **OPERATIONAL COVERAGE %** = active(off-probation) / 81 — trends to 100% = fully operational.
- **Active vs. probation**, **proposals pending approval** (open `gate:human-required` issues).
- **Per-class output, revenue/growth first** (LangSmith runs/tokens by class).
- **Day-over-day deltas** (▲/▼) via an appended `.tmp/daily-digest/scoreboard-history.jsonl`.
(Verified live: `STAFFED 15 / 81 (19%)`, coverage `0%` — everyone on probation — so the number
climbs visibly as agents are promoted.)

## Guarantees (load-bearing — enforced in code + tests, 209 tests green)
- **Report-only / propose-only:** cloud agents deliver via `file_digest_issue(..., report_only=
  <default True via OPS_REPORT_ONLY>)` → no GitHub write, **no approval interrupt**, so an
  unattended run never hangs or writes. QA engineers' outward actions stay gated; merges to
  prod repos are hard-blocked (`github_ops`).
- **Fail-safe:** every RC / GitHub / HTTP / filesystem / model call degrades to a structured
  result; missing keys → deterministic fallbacks. (Smoke-verified with **zero** credentials.)
- **Secrets:** env only, never logged. `memory_sync` excludes credential files + secret-pattern
  records (Gate B). **No over-claim:** the growth agents scan drafts for the
  `docs/growth/scheduler_positioning.json` `do_not_claim` list (time-tracking / AI scheduling)
  and flag rather than silently emit.
- **ML boundary:** `assert_not_model_work` + `gal-model` skip everywhere (Anthropic terms).
- **git guard alignment:** `git_sync_auditor` imports `git_local_maintainer._protected_activity`
  (it does not re-patch); strictly read-only (no push/fetch/remove/delete).

## Coordination with in-flight work
- **memory pipeline:** `memory_sync` is the executor *skeleton* for "Pipeline C" in
  `.tmp/remote-first-migration/INVENTORY-AND-PLAN.md`. The remote target is still undecided
  there, so the backend is pluggable and defaults to `dryrun`. Pick the backend when that
  session lands — don't invent a competing pipeline.
- **git guard:** the recency/unpushed guard is already merged on `phase-0-foundation`; the
  `.tmp/cron-guard/` patch targets the launchd runtime copy and is not re-applied here.

---

## ⛔ CONSOLIDATED ACTIVATION CHECKLIST — requires Shay's / operator sign-off

Everything above is **built, tested, registered, and staged**. Nothing below is done —
schedules are not loaded, nothing is deployed, all agents are report-only on probation. Do
these only after sign-off:

1. **Verify LangSmith key** present in the env (tracing is wired; key may be missing locally):
   `grep -q LANGSMITH_API_KEY <env> && echo present` (never print the value).
2. **Dry-run each surface and review the digest** (report-only, no writes):
   ```bash
   cd .../qa-agent-platform/worktrees/ops-fleet
   ./.venv/bin/python scripts/run_ops_graph.py daily_digest            # → .tmp/daily-digest/latest.md  (start here)
   ./.venv/bin/python scripts/run_ops_graph.py revenue_reporter
   ./.venv/bin/python scripts/run_ops_graph.py store_health_checker
   ./.venv/bin/python scripts/run_ops_graph.py conversion_growth_analyst
   ./.venv/bin/python scripts/run_ops_graph.py aso_store_listing_agent
   ./.venv/bin/python scripts/run_ops_graph.py content_campaign_drafter
   bash scripts/run_git_sync_auditor.sh        # → .tmp/git-sync-auditor/latest.md
   bash scripts/run_memory_sync.sh             # → .tmp/memory-sync/latest.md (dry-run)
   ./.venv/bin/python scripts/run_qa_assignment.py    # QA first assignment, report-only
   ```
3. **Load the launchd schedules** (each plist is `RunAtLoad=false`):
   ```bash
   cp docs/launchd/com.schedulersystems.{git-sync-auditor,memory-sync,revenue-reporter,store-health-checker,daily-digest}.plist ~/Library/LaunchAgents/ 2>/dev/null
   for L in git-sync-auditor memory-sync revenue-reporter store-health-checker daily-digest; do
     launchctl load ~/Library/LaunchAgents/com.schedulersystems.$L.plist
   done
   ```
   (`daily-digest` plist: add if you want the local daily run; otherwise schedule it on the platform.)
4. **(Cloud) deploy** the 6 cloud graphs via `langgraph deploy` (needs `LANGSMITH_API_KEY`; no GitHub OAuth).
5. **Provide creds to light up real data** (env, never logged): `REVENUECAT_API_KEY` +
   `REVENUECAT_PROJECT_ID` (funnel/SKU checks), a least-privilege GitHub App token
   (`FLEET_APP_ID` + key) for deploy-state reads + issue delivery.
6. **Promote off probation** (after 2 clean reviews, per roster policy): drop `OPS_REPORT_ONLY`
   / `GITHUB_OPS_REPORT_ONLY` (and set `AGENT_AUTONOMY=auto` for SAFE_AUTO `open_issue` delivery,
   or run attended) so the reporters file digests/alerts and growth agents post drafts. Watch the
   scoreboard's coverage % climb.
7. **(memory_sync) arm a real backend** once Pipeline C's target is decided:
   `MEMORY_SYNC_BACKEND=<langgraph_store|litestream|claude_memory_git>` + `MEMORY_SYNC_APPLY=1`.
8. **(QA) run the first assignment for real** (attended): `QA_ASSIGNMENT_DISPATCH=1
   ./.venv/bin/python scripts/run_qa_assignment.py` — dispatches e2e on the 4 blocked branches;
   approve any drafted writes interactively.

Kill switch for the whole fleet at any time: `export AGENTS_DISABLED=1`.
