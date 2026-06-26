"""Ops fleet — recurring operational roles, staffed as LangGraph agents.

These are the "keep-the-lights-on" employees (vs. the QA testers in ``graphs/qa/``):

  - ``git_sync_auditor``      (LOCAL launchd) — reports local↔remote git divergence across
                               the workspace; successor to git_local_maintainer's reporting
                               mission with the recency/unpushed guard built in. Read-only.
  - ``memory_sync``           (LOCAL launchd) — keeps local memory stores synced to a remote
                               target via a pluggable backend (dry-run on probation).
  - ``revenue_reporter``      (CLOUD)         — weekly RC metrics + deploy state + pipeline
                               digest.
  - ``store_health_checker``  (CLOUD)         — detects non-purchasable SKUs, offering/trial
                               drift, and paywall unreachability.

All start ``status: probation`` in report-only mode (no mutating actions without a human
gate), consistent with hr_ops_manager. The two LOCAL graphs need the local multi-repo
filesystem (like git_local_maintainer), so they are NOT in ``langgraph.json`` — they run via
``scripts/run_*.sh`` under launchd and trace to the SAME LangSmith project as the fleet.
"""
