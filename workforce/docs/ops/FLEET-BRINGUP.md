# Fleet bring-up — the one-grant-and-go runbook

**For the founder.** This answers "why do I have to keep pointing you?" The honest answer has two
parts: (1) the C-suite graphs are **built but not yet composed into this repo** (see the prerequisite
below), and (2) once composed, the only thing between "built" and "running themselves" is **one**
irreducible action — seeding the root of trust — because a from-zero agent cannot mint its own first
production credential. This runbook makes that **one yes** explicit and turns everything after it into
self-provisioning. After the single bootstrap, the fleet provisions its own per-agent identities and
reconciles itself; you are the constitution-setter, not a per-step approver.

> **Status: ready to flip, NOT flipped.** Everything here is reviewable artifacts + scripts.
> Nothing in this package deploys, writes a secret, or crosses a hard gate on its own. The
> actual bootstrap + deploy is yours to authorize once.

---

## 🔶 First, the prerequisite I found (the deeper answer to "why can't the C-suite work themselves")

The `agent-workforce` repo was archived 2026-06-18 and "folded into Scheduler (`workforce/`)" — but
**the fold was incomplete.** This live `workforce/` has only **~8 agents (the QA team + storage
maintainer)**. The full **32-agent C-suite** (CEO, CFO, COO, CTO, CMO, CISO, CLO, board×3, HR + growth
+ ops, with real LangGraph graphs) was **never composed in** — it is stranded on the unmerged
`feat/ops-fleet-prod-harden` branch of the now-archived `agent-workforce` repo. This is the
"~80% built across 30+ branches that don't compose" disease the org-design doc named.

So "make the C-suite run itself" has **two** prerequisites, in order:
1. **Compose the 32-agent C-suite into this `workforce/`** (finish the 2026-06-18 fold) — port the
   prod-harden roster + C-suite graphs + `langgraph.json` entries + tests. *A separate, large
   customer-repo campaign; queued to you, not done here.*
2. **The one Vault root grant** (this runbook, Step 0) — then identities self-provision.

This package (per-agent self-provisioning + the one-grant bootstrap) is **roster-agnostic**: it works
today for whatever is rostered and lights up fully for the C-suite the moment prerequisite (1) lands.

---

## What already exists (do NOT rebuild — compose it, don't refork)

| Piece | Where | State |
|---|---|---|
| **Workers (live)** | `roster.yaml` / `langgraph.json` (this repo) | QA team + storage maintainer (~8 agents), each an HR-rostered employee (salary, schedule, scorecard) |
| **C-suite + board (stranded)** | `agent-workforce` `feat/ops-fleet-prod-harden` (archived) | 32-agent roster + real CEO/CFO/COO/CTO/CMO/CISO/CLO/board graphs — **needs composing in (prereq 1)** |
| **Agent graphs** | `graphs/` — 1:1 with the roster, enforced by `scripts/check_roster_coverage.py` | real LangGraph implementations |
| **Runtime substrate (Stratus)** | `StratusCloudLabs/argocdgitops/clusters/stratus/workloads/gal-agents/` | k8s Deployments + per-agent ServiceAccount + Postgres checkpointer + ESO ExternalSecrets, synced by ArgoCD |
| **Secrets plane (Vault + ESO)** | `…/workloads/vault/`, `…/workloads/external-secrets/` | Vault KV v2 (`secret`), External-Secrets reads via `eso-reader` and delivers to pods |
| **Observability (LangFuse)** | `…/workloads/langfuse/`, `agent_toolkit/otel.py` | self-hosted LangFuse via OTel collector (in-cluster) |
| **Kill switch (stranded)** | `scripts/fleet_control.py` + `AGENTS_DISABLED`/`FLEET_DISABLED`/`AGENTS_BENCHED` — **on the archived prod-harden branch, NOT yet composed into this repo** | stops all / one agent immediately — **compose in (prereq 1)** |
| **Governance constitution (stranded)** | `governance/constitution.md` — **on the archived prod-harden branch** | spend/flip/identity/merge/escalation policies — **compose in (prereq 1)** |
| **Safety model (stranded)** | `docs/ops/safety-model.md` — **on the archived prod-harden branch** | every mutating capability stays behind a gate; probation = report-only — **compose in (prereq 1)** |

> ⚠️ **The fold was thin.** The 2026-06-18 archive of `agent-workforce` "into Scheduler `workforce/`"
> brought the 8-agent QA skeleton but left behind the kill switch, governance constitution, safety
> model, coverage gates, AND the 32-agent C-suite — all still on the archived `feat/ops-fleet-prod-harden`
> branch. **Prereq 1 (finish the fold) means composing ALL of that in, not just the C-suite.**

**This package adds the two genuinely-missing keystones** (and is self-contained — its code depends
only on `roster.yaml` + `langgraph.json` + `governance/privilege-classes.yaml`, all present here):
1. `scripts/provision_identity.py` + `governance/privilege-classes.yaml` — **per-agent self-provisioning** (constitution §3 was spec-only; this is the code).
2. `scripts/bootstrap_fleet.sh` + this runbook — **the single root grant**, codified (it was imperative + lost-on-rebuild per `VAULT-ACCESS.md`).

---

## ⚠️ North-Star correction (read before using the old runbook)

The runtime is **Stratus** (self-hosted k8s + ArgoCD + Vault + ESO) and observability is
**LangFuse** — per the frozen North Star (Shay, 2026-06-25, LangSmith dropped). The older
`docs/ops/ACTIVATION-RUNBOOK.md` and `scripts/check_deploy_env.py` still describe the **LangSmith**
managed-deploy path (`langgraph deploy --deployment-id …`, `LANGSMITH_API_KEY`). **That path is
STALE.** Use *this* runbook. (The LangSmith references should be swept to Stratus when those files
are next touched.)

---

## The cold-start checklist — exactly ONE founder action, then self-serve

### 🔴 STEP 0 — the ONE grant (founder / operator, ~15 min, HARD GATE)

This is the only thing that needs you. It seeds the root of trust so everything else can
self-provision. Run the bootstrap **in dry-run first** (changes nothing), read the plan, then apply:

```bash
cd <…>/Scheduler-Systems/Scheduler/workforce
scripts/bootstrap_fleet.sh                 # DRY RUN — prints the entire plan, changes nothing
scripts/bootstrap_fleet.sh --seed-checklist# the Vault paths to populate (names only, no values)
# when you're ready (Vault admin login + kube context):
scripts/bootstrap_fleet.sh --apply         # asks you to type a confirmation; idempotent
```

It does three things, all least-privilege, none of them "root for agents":
1. Vault **read** side: k8s auth + `eso-reader` bound to the ESO ServiceAccount (so secrets reach pods).
2. Vault **write** side: the scoped `gal-run-writer` policy + a *named operator* auth method (stop using root).
3. **You** paste the actual secret values into the listed Vault paths (`vault kv put …`) — the script
   never sees or prints a value.

> Why this is irreducible (and the ONLY thing that is): Vault is in-cluster, and a brand-new agent
> has no credential to authenticate with yet. Someone with cluster-admin + a Vault admin login has to
> establish the first identity. That someone is you, **once**. (The §3 rule — "granting a *new
> privilege class* … escalate"; everything *within* the existing classes is auto — is encoded in
> `governance/privilege-classes.yaml`, present here; the full `constitution.md` composes in with prereq 1.)

### 🟢 STEP 1 — per-agent self-provisioning (the ops-provisioner agent — NO founder action)

After Step 0, the **security_officer** agent holds the `ops-provisioner` class and mints every
other agent's own identity from the roster — you do **not** do this per-agent:

```bash
python -m scripts.provision_identity --check          # CI lint: every agent maps to a known class (fail-closed)
python -m scripts.provision_identity                  # generate per-agent Vault policy + AppRole + k8s SA + ExternalSecret
FLEET_BRINGUP_APPLY=1 python -m scripts.provision_identity --apply   # PRINT the operator apply plan
```

Each agent gets its **own** Vault AppRole + a policy that reads **only its own** `secret/data/gal-run/agents/<agent>/*`
subtree plus the shared material its **privilege class** allows (`governance/privilege-classes.yaml`).
No shared credentials; one leaked AppRole can't read a peer's secrets (proven by
`tests/test_provision_identity.py`: isolation, no-write, fail-closed, provision-is-ops-only).

### 🟢 STEP 2 — ArgoCD reconciles the workloads (GitOps — NO founder action)

The `gal-agents` workloads (Deployments, ServiceAccounts, ExternalSecrets, Postgres) are already in
the GitOps repo. ArgoCD syncs them; pods come up, read their scoped secrets via ESO, and listen on
`:8000`. A shift starts by POSTing `…/invoke/<graph>` (Scheduler triggers this when a shift opens —
the workforce layer).

### 🟢 STEP 3 — agents stay on probation (report-only) until they earn write (NO founder action)

Every agent is `status: probation` → report-only (the safety model + kill switch + coverage gates
compose in with prereq 1; they live on the archived prod-harden branch today). They observe, draft,
and propose; they do not merge/deploy/send/spend. They graduate per the constitution, not per your sign-off.

### 🔴 The kill switch is always one command (founder, anytime)

```bash
# set AGENTS_DISABLED=1 in the deployment env  → stops EVERYTHING immediately (works today)
# once fleet_control.py is composed in (prereq 1):
python scripts/fleet_control.py kill-all "reason"   # stop EVERYTHING immediately
python scripts/fleet_control.py bench <agent>       # stop ONE agent
```

---

## Founder-gated vs self-serve — the whole map

| Action | Who | Gate |
|---|---|---|
| Seed Vault root of trust (Step 0) | **founder/operator** | 🔴 HARD GATE (security baseline) — the one grant |
| Mint per-agent identities **within** existing classes | ops-provisioner agent | 🟢 auto (constitution §3) |
| Add or widen a **privilege class** | — | 🔴 escalate → founder (enforced: `provision_identity.py` refuses an unknown class) |
| Reconcile agent workloads | ArgoCD | 🟢 auto (GitOps) |
| Model-API / infra spend ≤ $2k/mo | CFO agent | 🟢 auto (constitution §1) |
| Merge reviewed non-prod / OSS PR | `pr-eval` | 🟢 auto (constitution §4) |
| Prod deploy / live billing / security-rules / paying-customer | escalate → **queue** | 🔴 founder (async, never blocks) |

---

## The honest ceiling (what this package does NOT prove)

- It is **verified in code + tests**, not yet **run against the live cluster** — Step 0 has never
  been applied (it's a hard gate). The dry-run is clean; the apply is yours.
- The per-agent AppRole wiring assumes Vault's `approle` auth backend is enabled; if it isn't, that's
  a one-line `vault auth enable approle` added to Step 0 (flagged in the bootstrap output).
- `privilege-classes.yaml` is a deliberately **small, closed** set (5 classes); 24 agents currently
  sit on the read-only floor by default — correct for report-only probation, but HR should assign an
  explicit class to each as roles solidify (`provision_identity.py --check` lists them every run).

**Bottom line for the founder:** the company is built. To make it run itself, you authorize the
**single** Step-0 bootstrap. After that one yes, identities self-provision, GitOps reconciles, and the
agents work on probation — and "point me at X" is replaced by "the fleet provisions X itself."
