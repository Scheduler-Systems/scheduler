# Safety & operating model — the agent company (auditable, one page)

Shay is **founder + investor with full override at all times**. The company runs itself; Shay
ratifies capital/irreversible/legal decisions and can intervene whenever. This page is the
auditable safety contract. If any item below is not true in code, it is a bug, not a policy.

## 1. Every mutating capability stays behind a gate
- **No merge / deploy / send / spend without approval.** Outward GitHub writes go through
  `agent_toolkit/github_ops.py`: default-DENY repo allow-list → report-only? → `AGENT_AUTONOMY=auto`
  SAFE_AUTO (only `open_issue`/`comment_issue`) → human approval gate. **Prod-repo merges are
  hard-blocked regardless of approval.** Reporters/officers deliver via `file_digest_issue(...,
  report_only=True)` by default → no GitHub call, no interrupt.
- **No autonomous spend / trades / billing / live-user actions** — not in any agent's scope.
- **do_not_claim compliance is mandatory** for every outward-facing draft (growth agents scan
  for the `docs/growth/scheduler_positioning.json` `do_not_claim` list and flag, never silently emit).

## 2. Budget hard-caps HALT, they don't overdraw
- `policy.per_run_token_ceiling` caps a single run; `salary_tokens_per_week` caps an agent/period.
- `check_clocked_in(agent)` returns **False** (the agent STOPS) when over budget — it does not
  borrow. The **CFO** owns budget allocation and proposes changes; the caps are its enforcement lever.
- Frugality is default: cheapest model grade that passes scorecards; escalate only on a flag.

## 3. Bench-on-anomaly + the kill switch (human override)
- **Bench-on-anomaly:** an agent that wedges or burns budget abnormally is benched; the rest of
  the shift/fleet continues (proven in the QA shift harness).
- **Per-agent kill:** bench any agent (`scripts/fleet_control.py bench <agent>` → `.payroll/benched.json`);
  `check_clocked_in` refuses a benched agent.
- **Fleet kill (one action):** `scripts/fleet_control.py kill-all` creates `.payroll/FLEET_DISABLED`
  (and/or set env `AGENTS_DISABLED=1`) → **every** agent's `check_clocked_in` returns False at once.
  Revive: `fleet_control.py revive-all`. The kill switch state + how to use it is surfaced in the
  **daily digest** so Shay always knows where it is.

## 4. Least-privilege credentials (no shared god-keys)
- Secrets are read from the environment only, never logged (error strings are type/status only).
- Each runtime gets only the scoped tokens it needs; the deploy/runtime env is **secret-free by
  default** (report-only agents need no GitHub/RC keys). Memory sync excludes credential files
  and secret-pattern records (Gate B). Per-agent deploy keys/secrets follow the cluster Vault
  pattern (see `mac-offload-plan.md`) — not one broad key shared across agents.

## 5. All actions logged + traceable
- LangSmith tracing where a key exists (the `scheduler-qa-fleet` project); local digests + a GAL
  governance capture otherwise. Every officer/agent run writes a digest and a `governance_capture`.

## 6. Small, containable waves
- Activation proceeds in waves (revenue + QA first, then ops, then departments by ROI), each
  **gated on scorecards + CFO budget sign-off**, each small enough that a misbehaving wave is
  contained. No mass-activation.

## 7. "Investor away" mode — operating without Shay for days
Shay is on duty and reachable only via phone updates. The fleet must keep working:
- **Gated items QUEUE, they never block.** Anything needing Shay is filed as a proposal in the
  digest / a `gate:human-required` issue and the agent CONTINUES with everything else. No agent
  fails because an approval is pending (report-only-by-default guarantees no blocking interrupt).
- **Escalation policy (assume days of silence):** ONLY **capital decisions** (budget increases,
  new paid services), **irreversible/production actions** (merges/deploys to prod, deletions),
  and **legal/ownership** matters escalate to Shay (`escalate_to: "shay"`). Everything else MUST
  resolve inside the org via the **CEO → CFO/hr_ops_manager** chain (`escalate_to: "org"`).
- **The board produces the one channel Shay reads:** the **investor update** (KPIs, decisions
  made, asks-if-any) leads the daily digest. If there are no asks, it says "no asks" — Shay can
  ignore it and the company still progresses.
- **Success metric:** "investor-touch-free days" — days the digest required zero Shay actions and
  output still shipped (tracked in the scoreboard). That is the definition of "works without me."

## Audit checklist (anyone can verify)
- [ ] `github_ops` prod-merge hard-block present; allow-list default-deny.
- [ ] reporters/officers default `report_only=True`; no reachable `request_approval`/`interrupt` on the unattended path.
- [ ] `check_clocked_in` honors `AGENTS_DISABLED`, `.payroll/FLEET_DISABLED`, `.payroll/benched.json`, over-budget.
- [ ] every officer proposal carries `escalate_to: org|shay`; only capital/irreversible/legal → shay.
- [ ] secrets env-only; deploy/runtime env secret-free; per-agent scoped creds.
- [ ] do_not_claim scan on every outward draft.
