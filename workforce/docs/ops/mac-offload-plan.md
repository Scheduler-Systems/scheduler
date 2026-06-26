# Mac offload — make this Mac a client, not a point of failure

Goal (Shay): the laptop ends as "just another client." Below is the honest architecture — a
lift-and-shift of the two local agents does NOT work, because they exist to observe the Mac's
local state. The real offload is three streams + a convergence with the sync session.

## The catch: the local agents are purpose-bound to the Mac
- `git_sync_auditor` audits **local↔remote git divergence** (unpushed/dirty/ahead-behind on this
  Mac's checkouts). Run it in-cluster on fresh GitHub clones and it audits nothing — a clone is
  always in sync. Its value evaporates once the Mac stops being authoritative.
- `memory_sync` syncs **this Mac's local memory stores** to remote. In-cluster it has no Mac
  memory to read. Its whole reason to exist is getting memory OFF the Mac.

So we don't containerize them as-is — we remove the *need* for them, and keep a thin reporter.

## Three offload streams
1. **Git → GitHub is the source of truth.** Push everything continuously (the sync session's
   `git-remote-sync` does this; the cloud `git_maintainer` handles GitHub-side branch hygiene). Once
   nothing authoritative lives only on the Mac, `git_sync_auditor` degrades to a thin **client
   hygiene check** ("is this Mac clean + pushed?") or retires. No cluster move needed.
2. **Memory → remote-authoritative (Litestream → GCS).** Continuous WAL replication of the SQLite
   stores (`claude-mem.db`, project memory) to GCS makes remote the source and the Mac a cache
   (the sync session's Pipeline C). `memory_sync` then becomes a **replication-health reporter**,
   not a syncer. **Remaining Mac dep:** the memory stores physically originate on the Mac and are
   read by Litestream there — until the capture pipeline itself is remote, the Mac is still the
   memory *source* (a cache that must stay replicated, not a hard dependency).
3. **Cloud agents → in-cluster (Stratus k3s via argocdgitops) or managed.** The whole LangGraph
   app (revenue/store/digest/growth/exec/board — everything not Mac-bound) runs as a container in
   the cluster, scheduled by in-cluster crons. **This is the durable substrate** (no macOS TCC,
   Mac-independent, 24/7). It is what makes "Shay sits back and gets updates" real.

## In-cluster deployment plan (argocdgitops conventions)
- **Image:** build the LangGraph Agent Server image from `langgraph.json` (remote/CI build — never
  the Mac, per orchestrate-local). Wolfi base, Postgres checkpointer injected by the platform.
- **GitOps:** add an Application + manifests under `StratusCloudLabs/argocdgitops` (agent-infra
  only — NOT scheduler product repos, which stay merge-held). Node constraints to the stationary
  nodes (ubuntu-1/2, lima-mac-mini) per the cluster taxonomy; not kali/mac-pro.
- **Secrets (least-privilege, Vault):** per-agent scoped tokens via the existing Vault pattern —
  a deployment-scoped LangGraph key, a least-privilege GitHub App token (feature-branch + read,
  no prod-merge), model keys. NO shared god-key. The runtime env stays report-only on probation.
- **Workspace:** any repo access = fresh `git clone` from GitHub inside the pod (source of truth),
  via the scoped GitHub App token — not the Mac's checkouts.
- **Crons:** in-cluster cron/Schedules drive the cadences (daily digest, daily store-health, the
  QA shift if/when it runs on cluster clones, the board meeting). Replaces the TCC-blocked launchd.

## Convergence with the sync session (avoid duplicate daemons)
The sync session installed launchd daemons `git-remote-sync`, `memory-langgraph-sync`,
`agentmode-sync` (all TCC-blocked, `runs=0`). These OVERLAP the roster agents. Converge:
- **Canonical = the roster-governed agents** (`roster.yaml` is the system of record).
- Memory: Litestream is the *mechanism*; `memory_sync` is the *roster-governed reporter* over it.
  Retire `memory-langgraph-sync`/`agentmode-sync` as separate daemons once Litestream + the reporter
  cover it. Coordinate with the sync session before either side removes the other's jobs (no-delete
  without agreement).
- Git: `git-remote-sync` (push) complements the read-only auditor — keep one pusher, one reporter.

## Remaining Mac-only dependencies (explicit, per Shay)
1. **Memory source** — the stores originate on the Mac until capture is remote (mitigated by
   continuous Litestream replication → Mac becomes a replaceable cache).
2. **This Claude Code conductor session** runs on the Mac (the human-in-the-loop console). Moving
   the *conductor* off-Mac is a separate decision (scheduled cloud Claude Code / a cluster runner).
3. **`git-local-maintainer`** (report-only, dormant, `runs=0`) — retire in favor of cloud
   `git_maintainer` + the client hygiene check.
4. **Local launchd anything** — being retired in favor of in-cluster crons (this plan).

## What's done vs. next
- **Done now:** this plan + the convergence decision + the secret-free report-only posture.
- **Next infra wave (focused, likely via the devops-engineer specialist):** build the image,
  author the argocdgitops Application + manifests + Vault secret wiring, deploy to k3s, verify
  health, cut over the cadences from launchd → in-cluster crons. Gated on: a deployment-scoped
  credential (the same one blocking the managed deploy) and argocdgitops merge. This is agent-infra
  GitOps (authorized) — not scheduler product repos.
