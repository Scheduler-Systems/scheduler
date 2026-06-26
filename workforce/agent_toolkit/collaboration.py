"""Make the agent team COLLABORATE in Slack along the ORG CHART, not just among the C-suite.

Background. The ambient watcher (scripts/channel_watcher.py) answers human messages, and this
module is the peer-to-peer layer on top: when ANY message (human OR agent) lands in a lane, decide
whether a DIFFERENT agent should chime in — so deliberation happens visibly in-thread instead of
each agent going quiet after one digest.

The founder's complaint: "the executives do not pass work to the team; I do not see enough
collaboration." Previously only the six C-suite roles (ceo/cfo/cto/qa/cmo/coo) talked to each
other; the ~20 WORKER agents (web/android/ios automation + manual testers, web_qa_regression,
conversion_growth_analyst, aso_store_listing_agent, content_campaign_drafter, sales_dev,
revenue_reporter, store_health_checker, daily_digest, env_doctor, git_maintainer, …) never
participated. This module now routes along the ORG CHART loaded from ``roster.yaml``:

  * DELEGATION (down). When a lane-owning exec is engaged on a task in its domain, the exec may
    hand the SPECIFIC piece to a REPORT in its department whose own skills/keywords fit best
    (e.g. cto → web_automation_engineer for a web-deploy/test item; cmo → aso_store_listing_agent
    for a listing item; cfo → conversion_growth_analyst for funnel data). The exec hands off; the
    report responds. One report per turn — never a fan-out to the whole department.

  * ESCALATION (up). A worker routes UP to ITS manager (manager_of) when something exceeds its
    scope. A worker never addresses a peer outside its lane and never skips a level to the CEO —
    it goes through its manager, who (being an exec) can then escalate further up the C-suite.

  * PEER (sideways, C-suite only). The original exec↔exec lane routing is preserved: a CFO budget
    flag still pulls in the CEO, a QA shippability concern still pulls in the CTO, etc.

The hard requirement is unchanged: the thread must stay SHUT. The chain is now DEEPER (it can be
exec→report→exec or report→manager→report), so the bound is re-derived (see MAX_DEPTH below): the
watcher caps each thread at MAX_DEPTH agent turns, gates every agent→agent turn through
``a2a_gate.gate_a2a`` (report-only), pins the depth counter against eviction, and escalates to Shay
at most once. Routing itself is pure keyword/org logic (NO model call); only the chosen agent's
``respond()`` costs a model call.

``route_collaboration`` / ``load_org_chart`` / ``manager_of`` / ``reports_of`` / ``dept_of`` are
pure (no LLM; the org chart is read once from the on-disk roster) and unit-tested directly.
"""
from __future__ import annotations

import os
import re

# --- depth bound ---------------------------------------------------------------------------------
# A thread may take at most this many AGENT turns before it is declared settled / escalated. A human
# message resets a thread to depth 0; each agent auto-reply increments it; at MAX_DEPTH the watcher
# stops auto-replying (and posts one "escalating to Shay" line if still unresolved).
#
# WHY 5 (was 3). The org chart adds two legs to the longest LEGITIMATE collaboration chain:
#   peer leg     : worker escalates UP to its manager           (report -> exec)           1 turn
#   delegate leg : the manager pulls in a different exec (peer)  (exec   -> exec)           1 turn
#   delegate leg : that exec delegates DOWN to one of its reports(exec   -> report)         1 turn
#   answer       : a peer/manager exec answers back                                          +2
# i.e. report->manager->peer-exec->that-exec's-report->settle is a real 4-hop hand-off; +1 head-room
# so a genuine delegation is never truncated mid-hand-off. It is a HARD cap, NOT a soft target:
# every other guard (per-thread counter, recency-pinned trim, a2a_gate, escalate-once) is unchanged,
# and the loop STILL terminates because depth increments every turn and route returns "settled" at
# the cap regardless of how the chain is shaped. Kept as small as a real delegation needs.
MAX_DEPTH = 5

# The six C-suite roles that own a lane and may talk sideways to each other. These role-keys match
# the watcher's CHANNELS role-keys AND map 1:1 to a deployed graph (see ROLE_TO_GRAPH) so the a2a
# gate can check the grant. Workers (loaded from the roster) are a SUPERSET handled below.
COLLAB_ROLES = ("ceo", "cfo", "cto", "qa", "cmo", "coo")

# The cross-functional arbiter. When a LANE owner posts in their OWN lane (e.g. the CFO flags a
# budget problem in finance) there is no peer to self-reply to — so it ESCALATES to the CEO, who
# owns company-wide priorities. The CEO in its own lane is already the top → no escalation peer.
ESCALATION_ROLE = "ceo"

# Which C-suite PEERS each exec is actually GRANTED to message (mirrors the message:<peer> grants in
# docs/governance/capabilities.yaml — the a2a_gate's allow-list). The router MUST NEVER emit an edge
# the gate would deny: a cross-department hand-off is therefore routed only to a peer the sender can
# reach. Every exec can reach the CEO (message:ceo), the CEO can reach every exec, and CTO<->QA hold
# each other; everyone else's only peer is the CEO. When the owning peer is NOT reachable, the
# cross-dept item is handed to the CEO (the cross-functional arbiter, reachable by all), who owns
# company-wide priorities and can route it onward into the owning lane on the next turn. This keeps
# the router and the capability manifest in lock-step so the watcher never drops a routed turn.
_PEER_MESSAGEABLE = {
    "ceo": {"cfo", "cto", "qa", "cmo", "coo"},  # CEO chairs the C-suite — may pull in any exec.
    "cfo": {"ceo"},                              # finance escalates to the CEO arbiter.
    "cto": {"ceo", "qa"},                        # CTO<->QA share a deploy/regression lane.
    "qa":  {"ceo", "cto"},                       # QA<->CTO (its shippability peer).
    "cmo": {"ceo"},                              # growth escalates to the CEO arbiter.
    "coo": {"ceo"},                              # ops escalates to the CEO arbiter.
}


def _peer_handoff(from_role: str, owning_exec: str) -> str:
    """The peer exec a cross-dept item from ``from_role`` may be handed to (gate-allowed).

    If the sender is GRANTED to message the lane's owning exec, hand off there directly (that exec
    then delegates inside its own department). Otherwise fall back to the CEO arbiter — the only peer
    every exec can reach — who can re-route into the owning lane. Never returns an edge the a2a_gate
    would deny."""
    if owning_exec in _PEER_MESSAGEABLE.get(from_role, set()):
        return owning_exec
    return ESCALATION_ROLE

# role-key -> deployed graph name (langgraph.json key / capabilities.yaml grant key). The watcher
# uses this to gate each agent→agent turn through a2a_gate with the REAL graph names. The C-suite
# keys differ from their graph names only for qa (role 'qa' -> graph 'qa_lead_aggregator'); every
# WORKER's role-key IS its graph name, so the worker entries are identity and added by the loader.
ROLE_TO_GRAPH = {
    "ceo": "ceo",
    "cfo": "cfo",
    "cto": "cto",
    "qa": "qa_lead_aggregator",
    "cmo": "cmo",
    "coo": "coo",
}

# Lane keyword map: which C-suite role OWNS a topic. First role whose keywords match wins the lane.
# Pure keyword routing — deterministic, cheap, no model call. Explicit addressing (below) overrides.
LANE_KEYWORDS = {
    "cfo": r"\b(budget|spend|cost|burn|salary|runway)\b",
    # NB: 'security'/'incident' are intentionally NOT CTO lane keywords — the dedicated CISO
    # (security_officer / Lior) OWNS the security domain (see _WORKER_KEYWORDS["security_officer"]).
    # Keeping them here would let _lane_target capture security items for the CTO (who holds no
    # message:security_officer grant), dead-ending them before they reach Lior. No duplicated lane
    # ownership: the security tokens live with the officer, the CTO keeps deploy/CI/build.
    "cto": r"\b(deploy|ci|pr|build)\b",
    "qa": r"\b(test|coverage|bug|shippability|regression)\b",
    "cmo": r"\b(growth|aso|conversion|revenue|funnel|listing)\b",
    # NB: bare "ops" is intentionally NOT a lane keyword — too generic ("our ops are running
    # smoothly", "DevOps"). The COO lane is signalled by specific operational terms instead.
    "coo": r"\b(operations|fleet|health|blocker|stale|outage)\b",
    "ceo": r"\b(strategy|priority|decision|escalate|proposal)\b",
}

# Explicit addressing: "@CFO", "CFO," or "CFO:" — an ADDRESS, not an incidental mention. OVERRIDES
# the lane so a message that DELIBERATELY addresses a peer routes there even if its keywords point
# elsewhere. Only the strong @mention / trailing-punctuation forms count; a bare role word in prose
# is an incidental MENTION, not an address.
_ADDRESS_ALIASES = {
    "ceo": ("ceo",),
    "cfo": ("cfo",),
    "cto": ("cto", "eng", "engineering"),
    "qa": ("qa", "qa lead", "qalead"),
    "cmo": ("cmo", "marketing"),
    "coo": ("coo", "ops"),
}

# =================================================================================================
# ORG CHART — loaded ONCE from roster.yaml (the authoritative org chart + payroll record).
# =================================================================================================
# roster.yaml ``org:`` groups the workforce by DEPARTMENT (board / executive / growth / qa / ops),
# each containing a C-suite manager and/or the worker agents reporting under it. We turn that into:
#   * dept_of(agent)    -> the roster department an agent belongs to.
#   * manager_of(agent) -> the C-suite ROLE-key a worker escalates UP to.
#   * reports_of(role)  -> the worker role-keys an exec may delegate DOWN to.
#
# Each roster department maps to the C-suite role that MANAGES it. This map is the one curated piece
# (the roster lists membership, not the manager↔dept binding); it is grounded in the exec graphs'
# own self-descriptions (cmo.py consumes the growth subordinates; coo.py consumes the ops
# subordinates; qa_lead_aggregator.py aggregates the platform workers; cto.py owns deploy/CI). The
# 'executive' and 'board' departments roll up to the CEO (the chair / top of the tree).
_DEPT_MANAGER = {
    "growth": "cmo",      # cmo.py: "the growth subordinates whose latest digests the CMO consumes"
    "ops": "coo",         # coo.py: "the OPS subordinate agents whose latest digests the COO consumes"
    "qa": "qa",           # qa_lead_aggregator.py: aggregates the platform worker verdicts
    "platform": "cto",    # platform_specialist (Lennox) owns the LangSmith runtime → CTO's domain
    "executive": "ceo",   # the CEO chairs the C-suite
    "board": "ceo",       # board rolls up to the CEO/founder
}

# A handful of qa-department workers are ENGINEERING agents whose delegated work (deploy/test
# tooling, CI regressions, env health, branch hygiene) is the CTO's domain even though the roster
# files them under qa for reporting. The CTO may DELEGATE down to these for an in-domain item; they
# still ESCALATE up to the qa lead (their roster manager) — managers and delegators can differ, and
# both edges are independently capability-gated. This list is the CTO's delegation reach; it never
# changes who a worker escalates to.
_CTO_ENGINEERING_REPORTS = (
    "web_automation_engineer", "android_automation_engineer", "ios_automation_engineer",
    "web_qa_regression", "env_doctor", "git_maintainer",
)

# Per-worker delegation keywords/skills: when an exec is engaged on an item in its domain, the report
# whose keywords best match the SPECIFIC piece is the one the exec hands off to (one per turn). Built
# from each worker's roster role text + its graph's stated job. Absent here, a worker can still
# escalate UP (escalation needs no keyword) but is not a delegation target.
_WORKER_KEYWORDS = {
    # --- CMO / growth ---
    "conversion_growth_analyst": r"\b(funnel|conversion|paywall|trial|mrr|churn|pricing|experiment)\b",
    "aso_store_listing_agent":   r"\b(aso|listing|store|keyword|metadata|reposition|app store|play store)\b",
    "content_campaign_drafter":  r"\b(content|campaign|email|blog|social|copy|newsletter)\b",
    "sales_dev":                 r"\b(lead|sales|pipeline|deal|prospect|follow[- ]?up|outreach)\b",
    # --- CTO / engineering (delegated from cto; escalate to qa lead) ---
    "web_automation_engineer":     r"\b(web|vitest|playwright|scheduler-web|frontend|e2e)\b",
    "android_automation_engineer": r"\b(android|espresso|junit|scheduler-android|apk)\b",
    "ios_automation_engineer":     r"\b(ios|xctest|scheduler-ios|simulator|xcode)\b",
    "web_qa_regression":           r"\b(regression|ci recon|web ci)\b",
    "env_doctor":                  r"\b(environment|dependency|env health|toolchain)\b",
    "git_maintainer":              r"\b(branch|merge|prune|hygiene|worktree|stale branch)\b",
    # --- QA lead / platform testers ---
    "web_manual_tester":     r"\b(web manual|exploratory web|web exploration)\b",
    "android_manual_tester": r"\b(android manual|emulator|exploratory android)\b",
    "ios_manual_tester":     r"\b(ios manual|exploratory ios)\b",
    # --- COO / ops ---
    "revenue_reporter":    r"\b(revenue report|weekly digest|rc metrics|pipeline state)\b",
    "store_health_checker": r"\b(store health|sku|purchasab|offering drift|paywall reach)\b",
    "daily_digest":        r"\b(daily digest|scoreboard|autonomy coverage|single pane)\b",
    "git_sync_auditor":    r"\b(git sync|divergence|unpushed|local.*remote)\b",
    "memory_sync":         r"\b(memory sync|memory store|store sync)\b",
    # --- CTO / platform (delegated from cto; escalate to cto) ---
    "platform_specialist": r"\b(langsmith|platform|eval gate|evaluator|online eval|feedback ledger|prompt hub|deployment revision|rollback|cron health|retention|otel)\b",
    # --- CEO / C-suite officers (delegated from ceo; escalate to ceo) ---
    # Lior (CISO) — operational-security lane: secure-by-design review, vuln/Sentry-security triage,
    # secret hygiene/rotation, incident response, prompt-injection/PII. Reports to the CEO.
    "security_officer": r"\b(security|threat|vuln|vulnerability|secret|incident|secure[- ]by[- ]design|replay|ssrf|prompt[- ]injection|pii|rotation|kill[- ]switch|sentry security)\b",
    # Lex (CLO) — legal lane: privacy/GDPR/Israeli-privacy, contracts/ToS/terms, billing terms,
    # compliance, breach notification, overclaim review, contractor classification. Reports to CEO.
    "clo": r"\b(legal|privacy|gdpr|contract|terms|tos|compliance|overclaim|breach notification|refund terms|classification|regulator)\b",
}


def _roster_path() -> str:
    """Absolute path to roster.yaml (worktree root). Overridable via COLLAB_ROSTER for tests."""
    override = os.environ.get("COLLAB_ROSTER")
    if override:
        return override
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "roster.yaml")


class OrgChart:
    """The org chart derived from roster.yaml: dept membership + manager/report edges.

    Pure data; built once. ``managers`` are C-suite role-keys; ``reports`` are worker role-keys
    (= their graph names). A worker's escalation manager is its roster department's manager; an
    exec's delegation reports are its department's workers PLUS, for the CTO, the engineering-tier
    qa workers it owns operationally.
    """

    def __init__(self, dept_members: dict[str, list[str]], deployed: set[str] | None = None):
        # dept_members: department -> [agent, …] exactly as roster.yaml org: lists them.
        # deployed: the set of agents that are actually deployed graphs (langgraph.json) and thus
        # GATEABLE / reachable in Slack. The ``deployed`` filter excludes any org-listed agent that
        # is not a deployed graph from DELEGATION targets — an exec can't hand Slack work to an agent
        # that isn't on a channel and has no capability grant. (LOCAL-ONLY launchd agents like
        # git_sync_auditor / memory_sync are NOT in roster.yaml org: at all as of 2026-06-07 — see
        # roster.yaml note — so dept_of(them) is None; this filter is the second line of defense.)
        # None => treat all as deployed (tests).
        self.dept_members = dept_members
        self._deployed = deployed

        # agent -> department (first department that lists it).
        self._dept_of: dict[str, str] = {}
        for dept, members in dept_members.items():
            for a in members:
                self._dept_of.setdefault(a, dept)

        # worker -> manager role-key (its department's manager). Exec roles are NOT workers and have
        # no manager here except via escalation-to-CEO handled by the router (ESCALATION_ROLE).
        self._manager_of: dict[str, str] = {}
        # manager role-key -> set of report worker role-keys it may delegate to.
        self._reports_of: dict[str, set[str]] = {r: set() for r in COLLAB_ROLES}

        exec_roles = set(COLLAB_ROLES) | {"qa_lead_aggregator"}
        for dept, members in dept_members.items():
            mgr = _DEPT_MANAGER.get(dept)
            for a in members:
                # A C-suite member of the 'executive'/'board' dept is not a worker-report.
                if a in exec_roles:
                    continue
                if mgr:
                    self._manager_of[a] = mgr
                    self._reports_of.setdefault(mgr, set()).add(a)

        # CTO's operational delegation reach over the engineering-tier qa workers (escalation
        # manager for those stays the qa lead — set above — so the two edges are independent).
        for w in _CTO_ENGINEERING_REPORTS:
            if w in self._dept_of:  # only rostered workers
                self._reports_of.setdefault("cto", set()).add(w)

    # --- public org-chart API ---------------------------------------------------------------
    def dept_of(self, agent: str) -> str | None:
        return self._dept_of.get((agent or "").strip().lower())

    def manager_of(self, agent: str) -> str | None:
        """The C-suite role-key a WORKER escalates UP to (None for execs / unknown agents)."""
        return self._manager_of.get((agent or "").strip().lower())

    def reports_of(self, role: str) -> tuple[str, ...]:
        """The DELEGATABLE report role-keys for an EXEC (sorted, deterministic).

        Only DEPLOYED (gateable, on-channel) reports are returned — a roster-only agent is excluded
        so the router never picks a delegation target the a2a_gate would have to deny / that has no
        Slack presence. Full department membership (incl. roster-only agents) is still in dept_of.
        """
        rpts = self._reports_of.get((role or "").strip().lower(), set())
        if self._deployed is not None:
            rpts = {r for r in rpts if r in self._deployed}
        return tuple(sorted(rpts))

    def is_worker(self, agent: str) -> bool:
        """True iff ``agent`` is a rostered WORKER (has a manager), not a C-suite role."""
        return (agent or "").strip().lower() in self._manager_of

    def all_workers(self) -> tuple[str, ...]:
        return tuple(sorted(self._manager_of))


_ORG_CACHE: OrgChart | None = None


def _deployed_graphs() -> set[str] | None:
    """The set of deployed graph names from langgraph.json, or None if unreadable (=> no filter)."""
    try:
        import json
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "langgraph.json")
        return set((json.loads(open(p).read()).get("graphs") or {}).keys())
    except Exception:
        return None


def load_org_chart(path: str | None = None, *, force: bool = False) -> OrgChart:
    """Load (and cache) the org chart from roster.yaml. Pure read; no LLM.

    Degrades safely: if the roster is missing/unreadable, returns an EMPTY org chart so the
    C-suite peer routing (which does not need the roster) still works — exactly the prior behavior.
    """
    global _ORG_CACHE
    if _ORG_CACHE is not None and not force and path is None:
        return _ORG_CACHE
    p = path or _roster_path()
    dept_members: dict[str, list[str]] = {}
    try:
        import yaml
        data = yaml.safe_load(open(p).read()) or {}
        org = data.get("org") or {}
        for dept, members in org.items():
            if isinstance(members, list):
                dept_members[dept] = [str(m).strip().lower() for m in members if m]
    except Exception:
        dept_members = {}
    chart = OrgChart(dept_members, deployed=_deployed_graphs())
    # Register every worker as graph-name==role-key so a2a_gate can resolve its grant.
    for w in chart.all_workers():
        ROLE_TO_GRAPH.setdefault(w, w)
    if path is None:
        _ORG_CACHE = chart
    return chart


# Module-level convenience wrappers (org chart loaded lazily on first use).
def dept_of(agent: str) -> str | None:
    return load_org_chart().dept_of(agent)


def manager_of(agent: str) -> str | None:
    return load_org_chart().manager_of(agent)


def reports_of(role: str) -> tuple[str, ...]:
    return load_org_chart().reports_of(role)


# =================================================================================================
# ROUTING
# =================================================================================================
def _explicit_target(text: str) -> str | None:
    """Return the C-suite role explicitly ADDRESSED in `text` (@ROLE / 'ROLE,' / 'ROLE:'), or None.

    Only the STRONG forms count: an `@role` mention, or a role alias immediately followed by `,`/`:`.
    Longer aliases first so 'qa lead' beats 'qa'.
    """
    low = text.lower()
    for role, aliases in _ADDRESS_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            if re.search(rf"(^|\W)@{re.escape(alias)}\b", low) or \
               re.search(rf"(^|\W){re.escape(alias)}\s*[,:]", low):
                return role
    return None


def _lane_target(text: str) -> str | None:
    """Return the C-suite role whose lane keywords match `text` first, or None (off-lane)."""
    low = text.lower()
    for role, pattern in LANE_KEYWORDS.items():
        if re.search(pattern, low):
            return role
    return None


def _best_report(role: str, text: str, chart: OrgChart) -> str | None:
    """Pick the single best report for ``role`` to DELEGATE this text to, or None.

    A report matches if its own keywords hit the text; among matches the one with the MOST
    keyword hits wins (most specific), ties broken alphabetically for determinism. One report per
    turn — never a fan-out. Returns None if no report's skills fit (then no delegation happens).
    """
    low = (text or "").lower()
    best: tuple[int, str] | None = None
    for rpt in chart.reports_of(role):
        pat = _WORKER_KEYWORDS.get(rpt)
        if not pat:
            continue
        hits = len(re.findall(pat, low))
        if hits <= 0:
            continue
        cand = (hits, rpt)
        # higher hits wins; on tie pick the alphabetically-first report (negate name for max()).
        if best is None or hits > best[0] or (hits == best[0] and rpt < best[1]):
            best = cand
    return best[1] if best else None


def route_collaboration(text: str, from_role: str, channel: str | None = None,
                        thread_depth: int = 0) -> tuple[str | None, str]:
    """Decide which agent should chime in on `text`, following the ORG CHART.

    Pure keyword + org logic — NO model call. Returns (target_role | None, reason).

    Resolution order:
      1. thread_depth >= MAX_DEPTH        -> (None, "settled")        — never ping-pong forever.
      2. sender is a WORKER               -> ESCALATE UP to manager_of(sender), if the topic
                                             exceeds its lane; never sideways to a peer, never
                                             straight to the CEO (only via its manager).
      3. sender is a C-suite role:
         a. explicit @address overrides the lane (C-suite peer addressing).
         b. else lane keyword match picks the owning C-suite role.
         c. if the owning role is the sender's OWN lane: try DELEGATING DOWN to the best-fit
            report in that exec's department; if no report fits, escalate own-lane flag to the CEO.
         d. if the owning role is a DIFFERENT exec: that's a cross-dept peer hand-off (sideways). Hand
            it to a GATE-REACHABLE peer — the owning exec when the sender is granted to message it
            (that exec then delegates DOWN to the fitting report inside its OWN lane), else the CEO
            arbiter (reachable by all). NEVER reach past the peer straight into a foreign worker — the
            sender holds no message grant for it and the gate would deny (the founder's complaint).
      4. never return the sender itself; only return a real, known agent the sender may message.
    """
    from_role = (from_role or "").strip().lower()
    text = text or ""
    chart = load_org_chart()

    # (1) Depth cap first.
    if thread_depth >= MAX_DEPTH:
        return None, "settled"

    # (2) A WORKER speaking → it may only ESCALATE UP to its own manager (org discipline: no
    # sideways peer contact, no level-skipping to the CEO). Escalation needs no keyword: a worker
    # that has raised something hands it to its manager, who decides whether it goes further.
    if chart.is_worker(from_role):
        mgr = chart.manager_of(from_role)
        if mgr and mgr != from_role:
            # Guard: a worker must never be routed to a peer outside its lane or to the CEO directly.
            return mgr, f"escalation: {from_role} -> {mgr} (manager)"
        return None, f"worker {from_role} has no manager — no escalation target"

    # (3) A C-suite role speaking.
    explicit = _explicit_target(text)
    if explicit is not None:
        target, reason_kind = explicit, "explicit-address"
    else:
        target, reason_kind = _lane_target(text), "lane-match"

    if target is None:
        return None, "off-lane (no peer owns this)"
    if target not in COLLAB_ROLES:
        return None, f"no real agent for lane '{target}'"

    # (3c) Owning role IS the sender's own lane.
    if target == from_role:
        if reason_kind == "explicit-address" or from_role == ESCALATION_ROLE:
            # Explicit self-address is a no-op; the CEO in its own lane is already the top.
            # But even in its own lane an exec may DELEGATE a concrete piece to a fitting report.
            rpt = _best_report(from_role, text, chart)
            if rpt is not None:
                return rpt, f"delegation: {from_role} -> {rpt} (own-lane report)"
            return None, f"own lane ({from_role}) — no self-reply"
        # Own-lane flag (not an explicit self-address): prefer DELEGATING DOWN to a fitting report;
        # only if none fits does the flag ESCALATE to the cross-functional arbiter (CEO).
        rpt = _best_report(from_role, text, chart)
        if rpt is not None:
            return rpt, f"delegation: {from_role} -> {rpt} (own-lane report)"
        return ESCALATION_ROLE, f"own-lane escalation: {from_role} -> {ESCALATION_ROLE}"

    # (3d) Owning role is a DIFFERENT exec — a cross-department peer hand-off. The sender must NEVER
    # reach PAST the owning exec into a foreign department's worker: an exec only holds message: grants
    # for the CEO + its OWN reports (+ a couple of peer execs), so a from_role -> foreign_worker edge is
    # default-denied by the a2a_gate and the watcher would silently DROP the turn — the founder's exact
    # complaint ("the executives do not pass work to the team"). Instead hand the item to a GATE-
    # REACHABLE peer exec: the OWNING exec directly when the sender is granted to message it (that exec
    # then delegates DOWN to the fitting report inside its OWN lane on its next turn — see 3c), else the
    # CEO arbiter (reachable by every exec), who routes it onward into the owning lane. Either way the
    # router only ever emits an edge the gate ALLOWS.
    peer = _peer_handoff(from_role, target)
    if peer == target:
        # Owning exec is directly reachable. Surface the intended downstream report (the concrete
        # piece its team will pick up) in the reason for observability, but route to the exec — the
        # delegation DOWN to its report happens on that exec's own turn (it owns the lane).
        if reason_kind != "explicit-address":
            rpt = _best_report(target, text, chart)
            if rpt is not None and rpt != from_role:
                return target, (f"peer hand-off: {from_role} -> {target} "
                                f"(to delegate -> {rpt})")
        return target, f"{reason_kind}: {from_role} -> {target}"
    # Owning exec NOT reachable from this sender → hand to the CEO arbiter (always gate-allowed).
    return peer, f"peer hand-off: {from_role} -> {peer} (arbiter for {target}'s lane)"
