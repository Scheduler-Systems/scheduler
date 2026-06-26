"""android_automation_engineer — Android automation engineer (v2).

Job: run scheduler-android's Gradle JUnit unit suite + Espresso instrumentation, then
summarize and classify each failure as flaky-vs-regression. TIER_DEFAULT model.

ORCHESTRATE-LOCAL, EXECUTE-ON-CLUSTER: this agent NEVER runs Gradle/emulators in its own
container. It DISPATCHES the heavy suites to CI (the scheduler-android `gate.yml` workflow:
`./gradlew test` unit + `./gradlew connectedDebugAndroidTest` Espresso on an API-34 AVD),
then POLLS GitHub Actions for the dispatched run, downloads the JUnit/Espresso result
artifacts, parses them, and orchestrates + summarizes the results with the model. A single
invocation now goes dispatch -> wait -> summarize end-to-end (no dispatch-and-stop) when a
GitHub token is configured; without one it degrades to the report-only dispatch path.

REPORT-ONLY: every outward/irreversible write (PR comment, bug issue, merge) is built first,
then gated through `request_approval`. The GitHub write-back is wired behind
`is_approved(decision)` AND the report-only switch (`GITHUB_OPS_REPORT_ONLY`, default ON for
this graph): in report-only mode `GitHubOps` returns the *intended* action as a plan dict and
NEVER calls GitHub — honest probation, never a fake success. The write only executes once the
switch is flipped off (a human decision) AND a human approves at the gate.

Maps audit specs: android-junit-gate-triage, android-espresso-triage.
Runtime: cloud/CI -> ARC runner (dispatch target = GitHub Actions).
"""
import io
import os
import time
import xml.etree.ElementTree as ET
import zipfile

from typing import Any
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from agent_toolkit import (
    budget_guard,
    check_clocked_in,
    request_approval,
    is_approved,
    span,
    governance_capture,
    assert_not_model_work,
    TIER_DEFAULT,
)
from agent_toolkit.github_ops import GitHubOps

try:  # works whether loaded as a package module or by file path (LangGraph platform)
    from .observe import is_observe_mode, read_local_repo_recon, render_recon
except ImportError:  # pragma: no cover - path-based load fallback
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from observe import is_observe_mode, read_local_repo_recon, render_recon

# scheduler-android test surface (from repo recon).
DEFAULT_REPO = "Scheduler-Systems/scheduler-android"
DEFAULT_WORKFLOW = "gate.yml"  # unit (./gradlew test) + Espresso (connectedDebugAndroidTest)
SUITES = ("gradle-unit", "espresso-instrumentation")
# Local checkout path (read-only) used by OBSERVE mode.
LOCAL_REPO_DIR = "scheduler-android"

_VERDICTS = {"pass", "regression", "flaky", "blocked"}

# --- CI-result fetch tuning (orchestrate-only; never runs the suite here) --------------
# workflow_dispatch returns NO run id, so we find the run by listing recent runs for the
# workflow+ref and picking the newest one created at/after we fired the dispatch.
_GH_API = "https://api.github.com"
_GH_TIMEOUT = 30.0
_POLL_INTERVAL_SECONDS = float(os.environ.get("ANDROID_CI_POLL_INTERVAL", "15"))
_POLL_MAX_SECONDS = float(os.environ.get("ANDROID_CI_POLL_TIMEOUT", "1800"))  # 30 min ceiling
# Trim the parsed CI payload we feed the model so a huge JUnit dump can't blow the token
# budget or leak internals (mirrors observe.py's _MAX_FILE_BYTES discipline).
_MAX_RESULTS_CHARS = 6000
_MAX_FAILURES_FED = 40


def _gh_token() -> str | None:
    """GitHub token from env only (never from code). Same precedence as dispatch.py."""
    return os.environ.get("GITHUB_DISPATCH_TOKEN") or os.environ.get("GITHUB_TOKEN")


def _write_report_only() -> bool:
    """Whether the GitHub WRITE-BACK stays report-only (honest probation; default ON).

    Default-DENY: this graph is deployed in REPORT-ONLY / PROBATION mode, so the write-back
    is report-only unless a human DELIBERATELY flips ``ANDROID_QA_WRITE_BACK=enabled`` (or the
    fleet-wide ``GITHUB_OPS_REPORT_ONLY`` is explicitly set to a falsey value). Even when the
    switch is off, every write still passes the per-action approval gate inside ``GitHubOps``,
    and a real write with no token configured FAILS CLOSED (it never fakes success). Merges
    are never built by this graph, so production-merge can't be reached from here.
    """
    explicit = os.environ.get("GITHUB_OPS_REPORT_ONLY")
    if explicit is not None:
        return explicit.lower() in ("1", "true", "yes")
    return os.environ.get("ANDROID_QA_WRITE_BACK", "").lower() != "enabled"


def _gh_headers(token: str) -> dict:
    return {
        "authorization": f"Bearer {token}",
        "accept": "application/vnd.github+json",
        "x-github-api-version": "2022-11-28",
    }


class State(TypedDict, total=False):
    # inputs
    mode: str               # "observe" -> read-only learning pass (no dispatch, no writes)
    observations: str       # OBSERVE-mode learning summary (read-only)
    repo: str               # GitHub owner/repo (default scheduler-android)
    ref: str                # branch/sha under test (default "main")
    workflow: str           # workflow file to dispatch (default gate.yml)
    pr_number: int          # PR to comment on, if any
    test_results: dict      # optional pre-fetched CI results to summarize (skips dispatch)
    # outputs
    dispatched: bool
    dispatch_detail: dict     # status code + body so a 403/404/422 is visible in the report
    run_url: str              # html_url of the polled GitHub Actions run (when found)
    run_conclusion: str       # success | failure | timed_out | cancelled | None
    verdict: str
    report: str
    approved: bool
    pending_writes: list
    writes_executed: list     # results of any GitHub write-back (report_only plan or real)


def budget_gate(state: State) -> dict:
    """CLOCK-IN gate: STOP the run if the agent is over its token salary or globally disabled.

    Fail-safe per `check_clocked_in`: when clocked out, produce a terminal 'clocked_out'
    report, capture governance, and end without dispatching, summarizing, or proposing
    any writes. When clocked in, this node is a no-op and the graph proceeds normally.
    """
    if check_clocked_in("android_automation_engineer"):
        return {}
    report = (
        "android_automation_engineer is over its token salary or globally disabled — "
        "skipping run"
    )
    with span("android_automation_engineer.budget_gate", clocked_in=False):
        governance_capture(
            "android_automation_engineer",
            {
                "mode": state.get("mode", ""),
                "repo": state.get("repo", DEFAULT_REPO),
                "ref": state.get("ref", "main"),
                "suites": list(SUITES),
                "clocked_in": False,
                "dispatched": False,
                "verdict": "clocked_out",
                "report_only": True,
            },
        )
        return {"verdict": "clocked_out", "report": report}


def plan(state: State) -> dict:
    repo = state.get("repo", DEFAULT_REPO)
    ref = state.get("ref", "main")
    workflow = state.get("workflow", DEFAULT_WORKFLOW)
    # Anthropic-terms guard on every target string we act on.
    assert_not_model_work(repo)
    assert_not_model_work(workflow)
    for suite in SUITES:
        assert_not_model_work(suite)
    with span("android_automation_engineer.plan", repo=repo, ref=ref, workflow=workflow):
        return {"repo": repo, "ref": ref, "workflow": workflow}


def observe(state: State) -> dict:
    """OBSERVE / learning mode — READ-ONLY. No CI dispatch, no proposed writes.

    Reads scheduler-android's local test setup (Gradle/JUnit/Espresso) + recent git
    history (read-only) and asks the model to produce an `observations` learning summary
    of how Android QA works and where it looks fragile. Report-only: no approval gate.
    """
    repo = state.get("repo", DEFAULT_REPO)
    ref = state.get("ref", "main")
    assert_not_model_work(repo)
    for suite in SUITES:
        assert_not_model_work(suite)
    with span("android_automation_engineer.observe", repo=repo, ref=ref, mode="observe"):
        facts = read_local_repo_recon(LOCAL_REPO_DIR)
        recon = render_recon(facts)
        observations = ""
        try:
            model = budget_guard("android_automation_engineer", TIER_DEFAULT)
            prompt = (
                "You are an Android QA automation engineer in LEARNING/OBSERVE mode for "
                "scheduler-android. You are NOT running or dispatching Gradle/Espresso; you are "
                "only studying the repo to understand how its QA works.\n"
                "From the READ-ONLY local recon below (Gradle JUnit unit + Espresso "
                "instrumentation setup and recent git history), write an 'observations' "
                "learning summary:\n"
                "1) How Android QA is structured (unit `./gradlew test` vs Espresso "
                "`connectedDebugAndroidTest`, build.gradle config, CI gate.yml).\n"
                "2) Where it looks FRAGILE/flaky-prone (emulator/AVD, ANR/timeout/race risk, "
                "Hilt test runner, churny areas in recent commits).\n"
                "3) What you would watch when you later run the real gate.\n"
                "Be concrete and cite filenames. Do not invent results.\n\n"
                f"{recon}"
            )
            resp = model.invoke(prompt)
            observations = getattr(resp, "content", str(resp)) or ""
        except Exception as exc:  # model unavailable — still report deterministic recon
            observations = (
                f"(model observe summary unavailable: {exc})\n\n"
                f"Read-only recon of {repo}:\n{recon}"
            )

        report = (
            f"android_automation_engineer OBSERVE (read-only learning) for {repo}@{ref}: "
            f"test_setup_files={facts.get('test_setup_files') or []}; "
            "no CI dispatched, no writes proposed."
        )
        governance_capture(
            "android_automation_engineer",
            {
                "mode": "observe",
                "repo": repo,
                "ref": ref,
                "suites": list(SUITES),
                "test_setup_files": facts.get("test_setup_files") or [],
                "dispatched": False,
                "report_only": True,
            },
        )
        return {"observations": observations, "report": report, "verdict": "observe"}


def _dispatch_workflow(repo: str, workflow: str, ref: str, inputs: dict) -> dict:
    """Fire a workflow_dispatch and CAPTURE the outcome (status code + body).

    The shared ``dispatch_github_workflow`` helper collapses everything non-204 to
    ``False``, hiding the real failure (404 workflow-not-found / 403 token-scope /
    422 bad-inputs). We do the same authenticated POST here but keep the status code
    and a trimmed body so a failed dispatch is VISIBLE in the report instead of
    silently becoming ``dispatched=False``. Token comes from env only; never raises.

    Returns ``{"ok": bool, "status": int|None, "detail": str, "dispatched_at": float}``.
    """
    token = _gh_token()
    if not token:
        return {"ok": False, "status": None, "detail": "no GITHUB_*_TOKEN in env",
                "dispatched_at": time.time()}
    import httpx

    fired_at = time.time()
    try:
        resp = httpx.post(
            f"{_GH_API}/repos/{repo}/actions/workflows/{workflow}/dispatches",
            headers=_gh_headers(token),
            json={"ref": ref, "inputs": inputs},
            timeout=_GH_TIMEOUT,
        )
    except Exception as exc:  # DNS/TLS/timeout — degrade, don't crash
        return {"ok": False, "status": None, "detail": f"dispatch error: {type(exc).__name__}",
                "dispatched_at": fired_at}
    ok = resp.status_code == 204
    detail = "accepted (204)" if ok else f"HTTP {resp.status_code}"
    if not ok:
        # GitHub returns a JSON error body on 403/404/422 — surface a trimmed slice of it
        # so the cause (e.g. "Workflow does not have 'workflow_dispatch' trigger") is seen.
        try:
            body = (resp.text or "")[:500]
        except Exception:
            body = ""
        if body:
            detail = f"HTTP {resp.status_code}: {body}"
    return {"ok": ok, "status": resp.status_code, "detail": detail, "dispatched_at": fired_at}


def dispatch(state: State) -> dict:
    """Dispatch the heavy suites to CI. Skipped if results were pre-supplied.

    Captures status code + body so a failed dispatch is visible in the report rather
    than collapsing silently to ``dispatched=False``.
    """
    if state.get("test_results"):
        return {"dispatched": False, "dispatch_detail": {"detail": "skipped: test_results supplied"}}
    repo = state["repo"]
    workflow = state["workflow"]
    ref = state["ref"]
    with span("android_automation_engineer.dispatch", repo=repo, workflow=workflow, ref=ref):
        info = _dispatch_workflow(
            repo=repo, workflow=workflow, ref=ref, inputs={"suites": ",".join(SUITES)}
        )
        return {"dispatched": bool(info.get("ok")), "dispatch_detail": info}


def _find_dispatched_run(token: str, repo: str, workflow: str, ref: str, since: float) -> dict | None:
    """Locate the run a workflow_dispatch just created.

    ``workflow_dispatch`` returns no run id, so we list recent runs for this workflow +
    ref (event=workflow_dispatch) and pick the newest one created at/after ``since``.
    Read-only GET; returns the run dict or ``None``. Never raises.
    """
    import httpx
    from datetime import datetime, timezone

    try:
        resp = httpx.get(
            f"{_GH_API}/repos/{repo}/actions/workflows/{workflow}/runs",
            headers=_gh_headers(token),
            params={"branch": ref, "event": "workflow_dispatch", "per_page": 20},
            timeout=_GH_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        runs = resp.json().get("workflow_runs") or []
    except Exception:
        return None
    # Allow small clock skew between our dispatch and GitHub's created_at stamp.
    floor = since - 120
    best: dict | None = None
    for run in runs:
        created = run.get("created_at") or ""
        try:
            ts = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            ).timestamp()
        except (ValueError, TypeError):
            continue
        if ts >= floor and (best is None or ts > best.get("_ts", 0)):
            run["_ts"] = ts
            best = run
    return best


def _safe_fromstring(xml_bytes: bytes):
    """Parse untrusted XML with XXE / billion-laughs defenses.

    Artifacts are downloaded over the network, so the JUnit/Espresso XML is untrusted.
    Prefer ``defusedxml`` if present; otherwise fall back to the stdlib parser but
    REFUSE any document carrying a DOCTYPE/entity declaration (the vector for external-
    entity and entity-expansion attacks). Returns an Element or raises ``ET.ParseError``.
    """
    try:  # best: defusedxml disables entity expansion + external DTDs outright
        from defusedxml.ElementTree import fromstring as _defused_fromstring  # type: ignore

        return _defused_fromstring(xml_bytes)
    except ImportError:
        pass
    # Fallback: stdlib parser, but block DOCTYPE so no entities can be declared/expanded.
    head = xml_bytes[:4096].lstrip()
    if b"<!DOCTYPE" in head.upper() or b"<!ENTITY" in xml_bytes[:8192].upper():
        raise ET.ParseError("refusing XML with DOCTYPE/ENTITY (XXE/billion-laughs guard)")
    return ET.fromstring(xml_bytes)


def _parse_junit_xml(xml_bytes: bytes) -> dict:
    """Parse one JUnit/Espresso XML report into {total, failures:[{name, type, message}]}.

    Handles a ``<testsuites>`` root or a single ``<testsuite>``. Never raises. XML is
    untrusted (downloaded artifact) so it goes through ``_safe_fromstring`` (XXE-guarded).
    """
    out = {"total": 0, "failures": []}
    try:
        root = _safe_fromstring(xml_bytes)
    except ET.ParseError:
        return out
    suites = root.iter("testsuite") if root.tag != "testcase" else [root]
    for suite in suites:
        for case in suite.iter("testcase"):
            out["total"] += 1
            classname = case.get("classname") or ""
            name = case.get("name") or ""
            full = f"{classname}.{name}".strip(".")
            for tag in ("failure", "error"):
                el = case.find(tag)
                if el is not None:
                    out["failures"].append(
                        {
                            "name": full,
                            "type": tag,
                            "message": (el.get("message") or (el.text or ""))[:500],
                        }
                    )
                    break
    return out


def _download_and_parse_artifacts(token: str, repo: str, run_id: int) -> dict:
    """Download the run's artifacts (zips of JUnit/Espresso XML) and parse to a results dict.

    Read-only GETs; FAIL-SAFE (any network/zip/XML problem degrades to a partial result,
    never an exception). Returns
    ``{artifacts:[names], total, failures:[...], parsed_from:int}``.
    """
    import httpx

    results: dict = {"artifacts": [], "total": 0, "failures": [], "parsed_from": 0}
    try:
        resp = httpx.get(
            f"{_GH_API}/repos/{repo}/actions/runs/{run_id}/artifacts",
            headers=_gh_headers(token),
            timeout=_GH_TIMEOUT,
        )
        if resp.status_code != 200:
            results["error"] = f"artifacts list HTTP {resp.status_code}"
            return results
        artifacts = resp.json().get("artifacts") or []
    except Exception as exc:
        results["error"] = f"artifacts list error: {type(exc).__name__}"
        return results

    for art in artifacts:
        name = art.get("name") or ""
        results["artifacts"].append(name)
        url = art.get("archive_download_url")
        if not url:
            continue
        try:
            dl = httpx.get(url, headers=_gh_headers(token), timeout=_GH_TIMEOUT,
                           follow_redirects=True)
            if dl.status_code != 200:
                continue
            zf = zipfile.ZipFile(io.BytesIO(dl.content))
        except Exception:
            continue  # not a zip / download failed — skip this artifact, keep going
        for member in zf.namelist():
            if not member.lower().endswith(".xml"):
                continue
            try:
                xml_bytes = zf.read(member)
            except Exception:
                continue
            parsed = _parse_junit_xml(xml_bytes)
            results["total"] += parsed["total"]
            results["failures"].extend(parsed["failures"])
            results["parsed_from"] += 1
    return results


def await_ci(state: State) -> dict:
    """Poll GitHub Actions for the dispatched run, wait for completion, fetch + parse results.

    Closes the dispatch-and-stop gap: after ``dispatch`` this node finds the run that the
    workflow_dispatch created (by listing recent runs for the workflow+ref), polls until it
    completes (bounded), then downloads the JUnit/Espresso artifacts and parses them into the
    ``test_results`` dict that ``summarize`` consumes. READ-ONLY + FAIL-SAFE + BOUNDED — it
    never runs the suite locally and never crashes the agent. Skipped when results were
    pre-supplied or the dispatch failed (no run to wait for).
    """
    if state.get("test_results"):
        return {}
    if not state.get("dispatched"):
        # Dispatch failed/never fired — nothing to poll. summarize() will report blocked
        # with the dispatch_detail so the 403/404/422 is visible.
        return {}
    token = _gh_token()
    if not token:
        return {}
    repo = state["repo"]
    workflow = state["workflow"]
    ref = state["ref"]
    since = (state.get("dispatch_detail") or {}).get("dispatched_at") or time.time()
    with span("android_automation_engineer.await_ci", repo=repo, workflow=workflow, ref=ref):
        deadline = time.time() + _POLL_MAX_SECONDS
        run: dict | None = None
        # 1) find the dispatched run (it can take a moment to appear).
        while time.time() < deadline:
            run = _find_dispatched_run(token, repo, workflow, ref, since)
            if run is not None:
                break
            time.sleep(_POLL_INTERVAL_SECONDS)
        if run is None:
            return {"run_conclusion": "not_found"}
        run_id = run.get("id")
        run_url = run.get("html_url") or ""
        # 2) poll the located run until it completes (bounded).
        import httpx

        conclusion = run.get("conclusion")
        status = run.get("status")
        while status != "completed" and time.time() < deadline:
            time.sleep(_POLL_INTERVAL_SECONDS)
            try:
                r = httpx.get(
                    f"{_GH_API}/repos/{repo}/actions/runs/{run_id}",
                    headers=_gh_headers(token),
                    timeout=_GH_TIMEOUT,
                )
                if r.status_code == 200:
                    body = r.json()
                    status = body.get("status")
                    conclusion = body.get("conclusion")
                    run_url = body.get("html_url") or run_url
            except Exception:
                continue  # transient — keep polling until the deadline
        if status != "completed":
            return {"run_url": run_url, "run_conclusion": "timed_out"}
        # 3) download + parse the JUnit/Espresso artifacts into the results dict.
        results = _download_and_parse_artifacts(token, repo, run_id)
        results["run_conclusion"] = conclusion
        results["run_url"] = run_url
        return {
            "test_results": results,
            "run_url": run_url,
            "run_conclusion": conclusion or "",
        }


def _trim_results_for_model(results: dict) -> str:
    """Serialize+trim the CI results for the prompt so a huge JUnit dump can't blow the token
    budget or leak internals (mirrors observe.py's byte-cap discipline)."""
    failures = results.get("failures") or []
    compact = {
        "run_conclusion": results.get("run_conclusion"),
        "total": results.get("total"),
        "artifacts": results.get("artifacts"),
        "failure_count": len(failures),
        "failures": failures[:_MAX_FAILURES_FED],
    }
    if results.get("error"):
        compact["error"] = results["error"]
    text = str(compact)
    if len(text) > _MAX_RESULTS_CHARS:
        text = text[:_MAX_RESULTS_CHARS] + " …(truncated)…"
    return text


def summarize(state: State) -> dict:
    """Use the model to summarize CI results and classify flaky-vs-regression."""
    repo = state["repo"]
    results = state.get("test_results") or {}
    with span("android_automation_engineer.summarize", repo=repo, has_results=bool(results)):
        if not results:
            # No results to summarize. Two distinct causes — make BOTH visible:
            #   * dispatch failed (403/404/422) — surface dispatch_detail so it isn't hidden;
            #   * dispatched OK but the poll could not retrieve results (no token / not found
            #     / timed out) — tell the caller to re-invoke with `test_results`.
            detail = state.get("dispatch_detail") or {}
            if not state.get("dispatched"):
                why = detail.get("detail", "dispatch did not succeed")
                return {
                    "verdict": "blocked",
                    "report": (
                        f"Dispatch of {', '.join(SUITES)} to "
                        f"{repo}::{state['workflow']}@{state['ref']} FAILED: {why}. "
                        "No CI run was started, so there are no results to classify."
                    ),
                }
            run_note = state.get("run_conclusion") or ""
            tail = f" (poll outcome: {run_note})" if run_note else ""
            return {
                "verdict": "blocked",
                "report": (
                    f"Dispatched {', '.join(SUITES)} to {repo}::{state['workflow']}@{state['ref']}. "
                    f"No CI results available to summarize yet{tail}; re-invoke with `test_results` "
                    "once the run completes."
                ),
            }

        prompt = (
            "You are an Android QA automation engineer for scheduler-android. Summarize the CI "
            "results below for two suites: Gradle JUnit unit tests (`./gradlew test`) and Espresso "
            "instrumentation (`./gradlew connectedDebugAndroidTest`, API-34 AVD).\n"
            "For EACH failing test, classify it as 'flaky' (timeout/emulator/race/network/"
            "ANR/flaky-by-history) or 'regression' (deterministic assertion/compile/logic failure).\n"
            "Then give ONE overall verdict, exactly one of: pass | regression | flaky | blocked.\n"
            "Be concise. Format:\n"
            "VERDICT: <pass|regression|flaky|blocked>\n"
            "SUMMARY: <2-4 lines>\n"
            "FAILURES:\n- <test> :: <flaky|regression> :: <why>\n\n"
            f"CI RESULTS (JSON):\n{_trim_results_for_model(results)}"
        )
        try:
            # budget_guard + invoke both inside the guard so a budget/model failure degrades
            # to a blocked verdict rather than crashing the agent (FAIL-SAFE).
            model = budget_guard("android_automation_engineer", TIER_DEFAULT)
            resp = model.invoke(prompt)
            report = getattr(resp, "content", str(resp))
        except Exception as exc:
            # Surface the failure TYPE only — never the raw results (may carry internals).
            return {
                "verdict": "blocked",
                "report": f"Model summarization failed: {type(exc).__name__}.",
            }

        verdict = _parse_verdict(report)
        return {"verdict": verdict, "report": report}


def gate(state: State) -> dict:
    """Build the proposed GitHub writes and gate them.

    REPORT-ONLY by default: this node records the human's batch decision; the actual write
    happens in ``finalize`` via the guarded ``GitHubOps`` surface, which stays report-only
    (returns plan dicts, no GitHub call) until the write-back switch is deliberately flipped
    off — so even an approval here does not perform a live write while in probation.
    """
    verdict = state.get("verdict", "blocked")
    repo = state["repo"]
    report = state.get("report", "")
    pr_number = state.get("pr_number")

    # Build the proposed outward actions (executed only later, guarded, and only if approved).
    pending: list[dict[str, Any]] = []
    if pr_number is not None:
        pending.append(
            {"action": "pr_comment", "repo": repo, "pr": pr_number, "body": report}
        )
    if verdict == "regression":
        pending.append(
            {
                "action": "open_bug_issue",
                "repo": repo,
                "title": f"[android-automation] regression on {state['ref']}",
                "body": report,
                "labels": ["bug", "android", "regression", "qa-agent"],
                # Stable key per repo+ref so a recurring regression updates ONE issue
                # (find-or-update) instead of filing a new bug every shift (#33/#35/#43-style spam).
                "dedup_key": f"android_automation_engineer:{repo}:{state['ref']}:regression",
                "agent": "android_automation_engineer",
            }
        )

    with span("android_automation_engineer.gate", verdict=verdict, pending=len(pending)):
        if not pending:
            # Nothing outward to do (e.g. clean pass, no PR) — no approval needed.
            return {"approved": False, "pending_writes": []}

        decision = request_approval(
            action="android_qa_github_writes",
            payload={"repo": repo, "verdict": verdict, "writes": pending},
            risk="high",
        )
        approved = is_approved(decision)
        # Report-only by default: even when approved here, finalize() routes the writes
        # through GitHubOps, which performs ZERO GitHub mutations while report-only is on.
        return {"approved": approved, "pending_writes": pending}


def _execute_writes(repo: str, pending: list[dict]) -> list[dict]:
    """Run the approved GitHub write-backs through the guarded ``GitHubOps`` surface.

    In report-only mode (the default — see ``_write_report_only``) ``GitHubOps`` returns a
    plan dict per action and NEVER calls GitHub: honest probation, never a fake success. With
    the switch flipped off it performs the real write, still passing GitHubOps' own allow-list
    + per-action approval gate, and FAILS CLOSED if no token is configured. FAIL-SAFE: any
    error becomes a structured ``{"status": "error", ...}`` so the run completes and surfaces
    the cause instead of crashing. Only ``pr_comment``/``open_bug_issue`` are emitted by this
    graph — never a merge — so production-merge is unreachable here.
    """
    ops = GitHubOps(report_only=_write_report_only())
    results: list[dict] = []
    for w in pending:
        action = w.get("action")
        try:
            if action == "pr_comment":
                res = ops.comment_issue(w["repo"], int(w["pr"]), w["body"])
            elif action == "open_bug_issue":
                res = ops.open_issue(
                    w["repo"],
                    w["title"],
                    w["body"],
                    labels=w.get("labels") or [],
                    dedup_key=w.get("dedup_key"),
                    agent=w.get("agent"),
                )
            else:
                res = {"status": "skipped", "action": action, "reason": "unknown action"}
        except Exception as exc:
            # Type-only — never str(exc) — so no token/URL in a message reaches the sink.
            res = {"status": "error", "action": action, "error": type(exc).__name__}
        results.append(res)
    return results


def finalize(state: State) -> dict:
    """Terminal node: execute the APPROVED writes (guarded), then governance-capture.

    The write-back is real code now, but stays REPORT-ONLY by default: ``_execute_writes``
    runs the approved actions through ``GitHubOps``, which returns plan dicts (no GitHub call)
    while the report-only switch is on. It performs real writes ONLY when a human both (a)
    flipped the switch off and (b) approved at the gate, and even then GitHubOps re-gates each
    action and fails closed with no token. Nothing here can merge or deploy.
    """
    verdict = state.get("verdict", "blocked")
    approved = state.get("approved", False)
    pending = state.get("pending_writes", [])
    report_only = _write_report_only()
    with span(
        "android_automation_engineer.finalize",
        verdict=verdict,
        approved=approved,
        pending=len(pending),
        report_only=report_only,
    ):
        # Only attempt the write-back when the agent-level gate approved the batch. In
        # report-only mode the call is still made (so probation produces the honest plan
        # dicts) but GitHubOps performs ZERO GitHub mutations.
        writes_executed: list[dict] = []
        if approved and pending:
            writes_executed = _execute_writes(state.get("repo", DEFAULT_REPO), pending)

        decision = {
            "repo": state.get("repo", DEFAULT_REPO),
            "ref": state.get("ref", "main"),
            "suites": list(SUITES),
            "dispatched": state.get("dispatched", False),
            "dispatch_detail": (state.get("dispatch_detail") or {}).get("detail"),
            "run_url": state.get("run_url"),
            "run_conclusion": state.get("run_conclusion"),
            "verdict": verdict,
            "approved_writes": approved,
            "pending_writes": [w.get("action") for w in pending],
            "writes_executed": [r.get("status") for r in writes_executed],
            # Honest label: True whenever the write-back did not perform a real GitHub write.
            "report_only": report_only or not writes_executed,
        }
        governance_capture("android_automation_engineer", decision)
        return {
            "report": state.get("report", ""),
            "verdict": verdict,
            "writes_executed": writes_executed,
        }


def _parse_verdict(report: str) -> str:
    """Extract the model's overall verdict; default to 'blocked' if unparseable.

    The structured ``VERDICT:`` line is authoritative — we read ONLY the token it names
    (longest-match so 'regression' isn't shadowed by a 'pass' substring) and never fall
    through to prose when a VERDICT line is present. The prose fallback (used only when the
    model omitted the line entirely) is negation-aware so phrases like 'no regression' /
    'not a regression' cannot flip the verdict to 'regression'.
    """
    for line in (report or "").splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("verdict:"):
            value = stripped.split(":", 1)[1].strip()
            # Longest-first so 'regression' wins over a stray 'pass' inside the value.
            for v in sorted(_VERDICTS, key=len, reverse=True):
                if v in value:
                    return v
            # A VERDICT line is present but names no known token — don't guess from prose.
            return "blocked"
    # Prose fallback (no VERDICT line). Strip negated mentions before substring-matching so
    # 'no regression' / 'not a regression' / 'without regression' don't read as a regression.
    low = (report or "").lower()
    for token in ("regression", "flaky", "pass"):
        if _mentions_positively(low, token):
            return token
    return "blocked"


_NEGATORS = ("no ", "not ", "without ", "zero ", "isn't ", "is not ", "aren't ", "no-")


def _mentions_positively(text: str, token: str) -> bool:
    """True if ``token`` appears in ``text`` at least once NOT immediately preceded by a
    negator (e.g. 'no regression', 'not a regression'). Cheap, dependency-free guard so an
    incidental negated phrase in the model's prose can't flip the overall verdict."""
    start = 0
    while True:
        idx = text.find(token, start)
        if idx == -1:
            return False
        window = text[max(0, idx - 16):idx]
        if not any(window.endswith(neg) for neg in _NEGATORS):
            return True
        start = idx + len(token)


def _entry(state: State) -> str:
    """Route to the read-only OBSERVE path or the normal dispatch path."""
    return "observe" if is_observe_mode(state) else "plan"


def _after_budget_gate(state: State) -> str:
    """After the CLOCK-IN gate: END if clocked out, else the normal observe/plan entry."""
    if state.get("verdict") == "clocked_out":
        return "__end__"
    return _entry(state)


builder = StateGraph(State)
builder.add_node("budget_gate", budget_gate)
builder.add_node("plan", plan)
builder.add_node("observe", observe)
builder.add_node("dispatch", dispatch)
builder.add_node("await_ci", await_ci)
builder.add_node("summarize", summarize)
builder.add_node("gate", gate)
builder.add_node("finalize", finalize)
# CLOCK-IN gate first: if over salary / globally disabled, stop before any work.
builder.add_edge(START, "budget_gate")
# OBSERVE mode bypasses dispatch + the approval gate entirely (read-only, report-only).
builder.add_conditional_edges(
    "budget_gate",
    _after_budget_gate,
    {"observe": "observe", "plan": "plan", "__end__": END},
)
builder.add_edge("observe", END)
# dispatch -> await_ci (poll GitHub Actions + fetch/parse artifacts) -> summarize, so a
# single invocation runs end-to-end. await_ci is a no-op when results were pre-supplied or
# the dispatch failed/has no token (summarize then reports blocked with the dispatch detail).
builder.add_edge("plan", "dispatch")
builder.add_edge("dispatch", "await_ci")
builder.add_edge("await_ci", "summarize")
builder.add_edge("summarize", "gate")
builder.add_edge("gate", "finalize")
builder.add_edge("finalize", END)

graph = builder.compile()  # NO checkpointer/store — injected by the platform
