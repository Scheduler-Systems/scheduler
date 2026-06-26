# Per-Agent Write-Enable Gate — graduating the fleet from report-only to WRITE, safely

> Status: enforced in code (`agent_toolkit/write_gate.py`), wired into the shared digest seam
> (`agent_toolkit/ops_report.file_digest_record`) and Posey's outward forward
> (`graphs/ops/email_triage.py::_report_only`). Tests: `tests/test_write_gate.py` (20),
> plus the existing seam/guard suites. Graduation itself is a **deployment env change — Shay's gate.**

## Why

Today every mutating/outward action is governed by a SINGLE global flag, `OPS_REPORT_ONLY`
(default report-only). Flipping it write-enables EVERYONE at once — Posey would forward email,
`git_maintainer` would prune, the propose-only officers would act. That is an unsafe,
all-or-nothing graduation.

The write-enable gate replaces "one global switch" with a **per-agent allowlist** so the proven,
low-risk agents are write-enabled first while everyone else stays report-only. The kill switch
(`check_clocked_in` / `AGENTS_DISABLED` / per-agent `AGENTS_BENCHED`) remains the master stop and
**composes** with the gate.

## The gate — `write_enabled(agent) -> bool` (default-DENY)

Returns `True` **only if ALL FOUR** hold (any failure ⇒ report-only; never raises):

1. **Floor lifted** — `OPS_REPORT_ONLY` is explicitly falsey (`0`/`false`/`no`/`off`).
   Unset or truthy ⇒ the global floor is ON and **nobody** is write-enabled.
2. **On the allowlist** — `agent` is named in `AGENTS_WRITE_ENABLED` (env, comma-separated).
   **Empty/unset ⇒ everyone report-only** (the default-deny floor).
3. **Not never-listed** — `agent` is NOT on the hard never-list (see below).
4. **Clocked in** — `check_clocked_in(agent)` is `True` (fleet not disabled, agent not benched,
   not over budget). The kill switch is the master stop, composed last.

`report_only_for(agent) == not write_enabled(agent)` is the seam the digest path and per-graph
`_report_only()` consult.

## Where it is wired (no guard changed)

* **`ops_report.file_digest_record`** (the shared digest seam EVERY agent uses): when the caller
  does not pin `report_only` (None) **or** asks to WRITE (`report_only=False`), the record is
  filed for real **only if `write_enabled(agent)`**; otherwise it is **withheld** (honest
  report-only plan dict, no GitHub call, no outward Slack post). An explicit `report_only=True`
  caller keeps the legacy RECORD-writes-on-probation behaviour (asking for report-only is always
  allowed; only asking to WRITE is gated). The downstream guards in `github_ops` — allow-list,
  **authorship**, **dedup**, RECORD-vs-CODE — are **untouched**.
* **`email_triage._report_only`** (Posey's outward invoice→Morning forward): derived from
  `report_only_for("email_triage")`. Posey is hard never-listed, so this is **always True** — the
  forward can never auto-send, even with `OPS_REPORT_ONLY=0` and even if Posey is mistakenly added
  to `AGENTS_WRITE_ENABLED`.
* **`store_ops` live-billing** writes remain fail-closed (`approve=True` AND `OPS_REPORT_ONLY` off);
  live billing is a founder HARD GATE and is not wired to any agent's autonomous path.

## Tiers (documented defaults — code constants in `write_gate.py`)

### TIER 1 — graduate FIRST (their write = a guarded GitHub record: deduped + authorship-guarded)
`cfo`, `ceo`, `cto`, `coo`, `board_chair`, `audit_risk_director`, `growth_director`,
`daily_digest`, `store_health_checker`, `revenue_reporter`

Recommended first graduation step (deployment env):
```
OPS_REPORT_ONLY=0
AGENTS_WRITE_ENABLED=cfo,ceo,cto,coo,board_chair,audit_risk_director,growth_director,daily_digest,store_health_checker,revenue_reporter
```

### TIER 2 — graduate LATER, after Tier 1 proves out (real guarded ACTIONS)
`git_maintainer` (prune — has the recency/unpushed guard), `web_qa_regression` + the QA bug-filers,
`hr_ops_manager`. Add to `AGENTS_WRITE_ENABLED` once Tier 1 is proven.

### HARD NEVER-LIST — can NEVER be write-enabled via the allowlist
Code constant: `security_officer`, `clo`, `platform_specialist` (propose-only officers),
`email_triage`/Posey (sends/forwards email), `cfo_deepagents` (broken).
**Plus** any agent whose capability grant in `capabilities.yaml` carries an
outward/irreversible verb (`send:` / `buy:` / `deploy` / `merge` / a standalone outward noun),
computed from the manifest so a new such agent is auto-blocked. A never-list agent stays
propose-only **even if added to `AGENTS_WRITE_ENABLED` and even with `OPS_REPORT_ONLY=0`** — the
never-list wins in code. (`git:prune_merged` is GUARDED, so a plain guarded `git:` prune is NOT
auto-never-listed — `git_maintainer` is gated as Tier 2 by being absent from the allowlist.)

## Graduation = a deployment env change (Shay's gate)

Graduating an agent is **two env vars on the LangSmith deployment**, never a code change:
1. `OPS_REPORT_ONLY=0` (lift the global floor), AND
2. add the agent's slug to `AGENTS_WRITE_ENABLED`.

`OPS_REPORT_ONLY` stays the **master report-only override / safety floor**: set it back to `1`
(or unset) and the whole fleet is report-only again regardless of the allowlist. The kill switch
(`AGENTS_DISABLED` / `.payroll/FLEET_DISABLED`, per-agent `AGENTS_BENCHED`) is the master stop and
overrides everything.

## Env reference

| Var | Meaning | Default |
|---|---|---|
| `OPS_REPORT_ONLY` | Master report-only floor. Truthy/unset ⇒ everyone report-only. `0` lifts the floor so the per-agent allowlist applies. | unset ⇒ report-only |
| `AGENTS_WRITE_ENABLED` | Comma-separated agent slugs that MAY write once the floor is lifted (and not never-listed, and clocked-in). | empty ⇒ nobody |
| `AGENTS_DISABLED` / `.payroll/FLEET_DISABLED` | Fleet-wide kill switch (master stop). | off |
| `AGENTS_BENCHED` / `.payroll/benched.json` | Per-agent kill switch. | empty |
