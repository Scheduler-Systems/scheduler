# EPIC: Scheduler QA Agent Fleet (LangGraph)

Source: workspace audit 2026-06-04 (81 processes).
Status: **Phase 0 (foundation) in progress.**

## Decisions
- **Home:** this monorepo (`gal-run/agent-workforce`). Marketing = fast-follow (sibling project / second LangSmith project for secret blast-radius).
- **Deploy:** self-host on Stratus by default (autonomous); managed via `langgraph deploy` once a `LANGSMITH_API_KEY` exists. No GitHub OAuth needed either way.
- **Architecture:** one `langgraph.json`, many graphs, shared `agent_toolkit`, GAL + OTel as middleware.

## Phase 0 — Foundation (this commit)
- [x] Repo + `langgraph.json` (multi-graph) + `pyproject.toml`
- [x] `agent_toolkit`: approval (interrupt gate), otel, governance hook, dispatch, policy (Anthropic-terms guard)
- [x] Canary `hello-gate` graph (validates deploy + interrupt/resume + OTel + governance)
- [ ] Validate end-to-end: Postgres injected, `interrupt()`/`Command(resume)` round-trip, OTel traces land, GAL hook fires

## Phase 1 — Scheduler 6 + 1 QA fleet (this is what Shay asked for)
- [ ] `qa_lead_aggregator` — coordinator → one verdict   _(audit: qa-test-aggregator / qa-test-orchestrator, P0)_
- [ ] `web_automation_engineer` — Vitest + Playwright   _(vitest-gatekeeper, e2e-playwright-orchestrator)_
- [ ] `android_automation_engineer` — JUnit + Espresso   _(android-junit-gate-triage, android-espresso-triage)_
- [ ] `ios_automation_engineer` — XCTest   _(ios-xctest-qa-orchestrator)_
- [ ] `web_manual_tester` — headless browser   _(qa-manual-pass-orchestrator)_
- [ ] `android_manual_tester` — emulator (Stratus Mac node)
- [ ] `ios_manual_tester` — simulator (Stratus Mac node)
- All start **report-only / dry-run**; writes (PR comments, bug issues) approval-gated. iOS degrades gracefully (~13/31 screens).

## Phase 2+ — broader fleet
Per-repo gatekeepers, release/security sentinels, marketing Brevo/content agents, E2E, hygiene/SEO.

## Open questions (need Shay)
1. One vs two deployments (QA GitHub creds vs marketing Brevo/PII isolation). Default: one repo, two LangSmith projects.
2. GAL governance endpoint (agent-governance epic go-services#37 not yet built — hook is fail-safe no-op until then).
3. Audit-flagged prereqs: Brevo template/list IDs null; `emulator-e2e.yml` missing; SPF/DKIM/DMARC undocumented.
4. Runner backend per agent class (ARC vs GAL Swarm vs GH Actions; macOS runner cost for iOS).

## GitHub
- [x] Create `gal-run/agent-workforce` on GitHub + this epic + 7 sub-issues.
