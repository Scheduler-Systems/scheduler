> ⚠️ **Development / experimental — NOT part of the Scheduler product.**
> This directory is an internal **LangGraph** agent fleet (an ML-boundary
> component). It is **not** part of the self-hostable Scheduler product, is **not
> built, run, or supported** by the released app, and is excluded from the
> product CI. It lives here for development reference only. The shippable product
> is `services/api`, `apps/web`, `apps/{ios,android}`, and `packages/core`.

# agent-workforce

Deployed **LangGraph** agents that automate Scheduler's **QA** (and, as a fast-follow, **Marketing**) processes. **One monorepo, many graphs, one shared toolkit** — not 60 copy-pasted repos.

Built from a 2026-06-04 workspace audit of 81 QA + Marketing processes; the build plan and fleet roadmap live in `EPIC.md`.

## Architecture
- `langgraph.json` declares every agent as a separate **graph** (an addressable assistant) in **one** deployment.
- `agent_toolkit/` — the shared library every graph imports:
  - `approval.py` — human-in-the-loop **approval gate** (`interrupt()` → `Command(resume=…)`). The load-bearing primitive: nothing irreversible ships without it.
  - `otel.py` — fail-safe OpenTelemetry instrumentation.
  - `governance.py` — GAL governance hook (captures every run's decision; fail-safe no-op until the endpoint exists).
  - `dispatch.py` — remote-runner dispatch (heavy test execution runs on ARC/GAL-Swarm/GitHub Actions, **never** in the agent container).
  - `policy.py` — **Anthropic-terms guard**: agents do orchestration only; a denylist hard-blocks any model train/eval/distill surface (`gal-model`, eval-worker).
- Graphs **compile WITHOUT a checkpointer/store** — managed platform injects Postgres; self-host supplies its own.

## The Scheduler QA fleet (v1 — 6 + 1)
| Platform | Automation Engineer | Manual Tester (device-bound → Stratus Macs) |
|---|---|---|
| **Web** | `web_automation_engineer` (Vitest + Playwright) | `web_manual_tester` (headless browser) |
| **Android** | `android_automation_engineer` (JUnit + Espresso) | `android_manual_tester` (emulator) |
| **iOS** | `ios_automation_engineer` (XCTest) | `ios_manual_tester` (simulator — macOS only) |
| — | `qa_lead_aggregator` — dispatches the six, emits one merge-gate / "is Scheduler shippable?" verdict | |

## Runtime placement
- Automation engineers + web-manual → cloud/CI (self-host or managed).
- **Android/iOS manual testers → Stratus Mac nodes** (sim/emulator cannot run on a Linux cloud).
- Heavy execution → **ARC runners / GAL Swarm / GitHub Actions**, never inside the agent (orchestrate-local, execute-on-cluster).

## Deploy
- **Self-host (default, autonomous):** build the Agent Server image → Stratus k3s with a Postgres checkpointer. No external account.
- **Managed (LangGraph Platform):** needs a LangSmith account + `LANGSMITH_API_KEY`, then `langgraph deploy` (CLI — **no GitHub OAuth**).

## Model routing (cost-first)
Routing lives in `agent_toolkit/models.py` — change it in one place, re-route the whole fleet.
- **Default tier → DeepSeek** (`deepseek-chat`) — ordinary agent reasoning (automation engineers, `qa_lead_aggregator`).
- **Escalation tier → Claude Haiku 4.5** (or OpenAI gpt-mini via `ESCALATION_PROVIDER=openai`) — **only** for browser automation, computer use, and complex tasks (the manual-tester agents).
- Graceful fallback: if a tier's provider key is missing, it falls back to whatever IS configured.
- Verify: `python scripts/smoke_models.py` (add `--ping` for a live 1-token call per tier).

## Guardrails
- Every send/publish/merge/delete is **approval-gated**; agents open PRs, humans merge.
- Secrets via env only (`.env.example` lists names) — never committed.
- iOS agents degrade gracefully against the incomplete native app.

See `EPIC.md` for the build plan and the full fleet roadmap.
