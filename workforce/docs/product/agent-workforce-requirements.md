# Requirements: "Multiplier for Agents" — Scheduler agent-workforce / org-structure feature

**Status:** spec input for the dedicated product session building the ADR-0006 feature.
**Data source of record:** `Scheduler-Systems/qa-agent-platform/roster.yaml` (the org chart +
payroll + HR record for the deployed agent workforce). Scheduler is the *visualization*; the
roster stays authoritative until a real bridge exists.

## Why this is a NEW feature (not the schedules feature)
Course-correction from Shay: **work schedules ≠ company structure.** The existing `schedules`
feature legitimately models *who works which shift* — it must NOT be overloaded to represent the
org chart. The org/workforce view is a distinct product surface (think the "Multiplier" HR
platform Scheduler used, but for AI agents). Keep only genuine work-scheduling in `schedules`
(e.g. QA's daily 2h shift can become a real shift later).

## What the feature must represent (from roster.yaml)
roster.yaml already encodes a richer org than Scheduler's humans-only model can express:

1. **Org hierarchy (multi-level, above departments):**
   `Board → CEO → Executives (CFO/COO/CTO/CMO) → hr_ops_manager → class leads → workers`.
   - Board: `board_chair`, `audit_risk_director`, `growth_director`.
   - Departments/classes today: `growth` (revenue), `qa` (quality), `ops` (keep-the-lights-on).
   - Scheduler gap: today it has tenants → schedules → employees (≈2 levels). It needs an
     **N-level org tree** (board/exec/department/team/individual).

2. **Leadership / departments:** each department has a lead (e.g. `qa_lead_aggregator`) and
   members; departments roll up to executives, executives to the CEO, CEO to the board.
   Scheduler gap: no concept of "manager-of-managers" or department→executive rollup.

3. **Agent (employee) metadata** — first-class fields per employee, none of which Scheduler
   models today:
   | Field | roster.yaml source | Notes |
   |---|---|---|
   | role / title | `agents.<name>.role` | free text |
   | model grade | `agents.<name>.grade` | e.g. `gemini-2.5-flash` — the "seniority/pay band" |
   | salary / budget | `agents.<name>.salary_tokens_per_week` | token budget per period |
   | status | `agents.<name>.status` | `probation` / active / benched |
   | scorecard | `agents.<name>.scorecard` | error_rate, false_positive_rate, useful_actions, tokens_spent |
   | shift / cadence | `agents.<name>.schedule` | e.g. "daily 09:30", "weekly Mon", "hourly" |
   | class / department | roster `org.{growth,qa,ops}` | grouping |
   | kind | (new) | **agent** vs human — the entity is an AI agent, not a person |

4. **Shifts linkage (the legitimate schedules overlap):** an employee's `schedule`/cadence
   (QA daily 2h, reporters daily, board meeting cadence) is the ONE field that may bridge into
   the real `schedules` feature later. Model the org-view's "shift" as a *reference* to a real
   schedule entry, not a copy.

## Hard constraint — identity / entitlement compatibility (carries over)
The pending IDOR entitlement gate matches `employees[]` by `user_ref` OR verified
`employee_email`. Any agent-employee rendered in the product must either (a) carry a real auth
account with a verifiable email, or (b) be explicitly flagged **roster-display-only (no app
login)** so the org view does not break when the security fix deploys. Prefer (b) for agents
unless an agent genuinely needs an app identity. Do not special-case the entitlement rules.

## Explicit gaps = the product asks (don't hack the existing model to fake these)
- N-level org hierarchy above departments.
- Non-human employee kind + agent metadata (grade/salary/status/scorecard) as structured fields.
- Rollup/aggregation (department spend, class headcount, org-wide burn) for the exec/board views.
- "Bench" status (hired, ~0 budget, not active) distinct from active.
- A read model that can be populated FROM roster.yaml (the bridge — see ADR-0006). Until then,
  the product view can be seeded read-only from a roster export.

## Suggested phasing
1. Read-only org tree seeded from a roster.yaml export (no writes, no bridge).
2. Agent-employee metadata fields + non-human kind.
3. Live bridge (roster.yaml ⇄ product) per ADR-0006 — the system of record stays roster.yaml.

Owner of the data contract: this repo's `roster.yaml` + `agent_toolkit/payroll.py` (the loader).
A roster→JSON export helper can be added here on request to feed the product session.
