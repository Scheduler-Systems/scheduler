"""Seed eval cases for the scheduler-qa offline evaluation dataset.

This is the LOCAL fixture half of the dataset (the part that needs NO creds): a list of
known-good (input, reference-output) examples drawn from the agents' REAL digests /
verdicts. ``scripts/run_eval.py`` seeds these into the LangSmith dataset
``scheduler-qa-eval``; the eval gate (``scripts/eval_gate.py``) and
``agent_toolkit.evaluations`` can run a target over them WITHOUT any network when a
local/in-memory dataset is used.

WHY here (not inline in run_eval): the gate, the runner, and the provisioning script all
need the SAME cases. Putting them in one module keeps the dataset definition single-source
and lets tests import the fixtures directly.

Anthropic-terms posture (workspace AGENTS.md): these are QA/ops AGENT-OUTPUT examples —
"did the agent produce a correct, useful verdict / digest?". They contain NO model
training/eval/distill content; the denylisted ``gal-model`` surface is explicitly NOT a
case here (the agents never QA it).

Each case shape (LangSmith-example compatible):
    {"inputs": {...}, "outputs": {"expected": "<reference good answer>"}, "metadata": {...}}

The reference ``expected`` text is what a GOOD agent answer looks like — the LLM-as-judge
scores the agent's actual output against it for correctness + usefulness.
"""
from __future__ import annotations

from typing import Any

# Public identifiers (NOT secrets).
DATASET_NAME = "scheduler-qa-eval"


# ---------------------------------------------------------------------------
# QA cases — observe-mode read-only QA tasks across the Scheduler platforms.
# (These preserve the original 4 toy cases so the LangSmith dataset stays stable.)
# ---------------------------------------------------------------------------
_QA_CASES: list[dict[str, Any]] = [
    {
        "inputs": {"target": "Scheduler-Systems/scheduler-web", "mode": "observe"},
        "outputs": {
            "expected": (
                "A concrete read-only observation of scheduler-web QA: Vitest unit + "
                "Playwright e2e setup, gate.yml CI surface, and where it looks flaky."
            )
        },
        "metadata": {"suite": "qa", "platform": "web"},
    },
    {
        "inputs": {"target": "Scheduler-Systems/scheduler-android", "mode": "observe"},
        "outputs": {
            "expected": (
                "A concrete read-only observation of scheduler-android QA: JUnit unit + "
                "Espresso instrumented setup and where it looks fragile."
            )
        },
        "metadata": {"suite": "qa", "platform": "android"},
    },
    {
        "inputs": {"target": "Scheduler-Systems/scheduler-ios", "mode": "observe"},
        "outputs": {
            "expected": (
                "A concrete read-only observation of scheduler-ios QA: XCTest setup, "
                "CI surface, and where it looks fragile."
            )
        },
        "metadata": {"suite": "qa", "platform": "ios"},
    },
    {
        "inputs": {
            "target": "Scheduler-Systems/scheduler-web",
            "mode": "observe",
            "note": "cross-platform: relate web QA to the shared scheduler product surface",
        },
        "outputs": {
            "expected": (
                "A cross-platform read-only observation relating one platform's QA to the "
                "shared scheduler product surface (auth, schedule build, billing)."
            )
        },
        "metadata": {"suite": "qa", "platform": "cross"},
    },
]


# ---------------------------------------------------------------------------
# Exec/ops cases — drawn from the agents' REAL digest shapes (NOT toy text).
# These are the "+a couple ops cases" the task asks for, plus the CFO conversational
# case, so the dataset exercises the prompts that actually change at redeploy
# (conversational-CFO + governed-prompt-pull).
# ---------------------------------------------------------------------------
_EXEC_OPS_CASES: list[dict[str, Any]] = [
    {
        # The CFO conversational case — directly exercises the prompt under change.
        # A question ("answer mode") must be answered DIRECTLY with the real figures,
        # report-only, no post, concise.
        "inputs": {
            "agent": "cfo",
            "mode": "answer",
            "question": "What's our token spend versus salary this period, and is anything off?",
            # The financial picture the CFO would read from get_financial_picture (real shape).
            "report": (
                "Period spend = $41.20 across 23 agents (token-budget salaries total $60.00). "
                "Burn is 69% of salary. One anomaly: web_manual_tester at $9.80 is 2.1x its "
                "$4.60 salary band. Report-only on probation — no money moved."
            ),
            "summary": "CFO conversational answer about spend vs salary.",
        },
        "outputs": {
            "expected": (
                "A direct, concise (1-3 sentence) plain-language answer giving the SPECIFIC "
                "figures: total spend (~$41.20) vs total salary (~$60.00), ~69% burn, and the "
                "one anomaly (web_manual_tester ~2x its band). No emoji, no markdown, no "
                "preamble; states it is report-only / no money moved. Does NOT post a digest."
            )
        },
        "metadata": {"suite": "exec", "agent": "cfo", "mode": "answer"},
    },
    {
        # The CFO shift-update case — no question => post EXACTLY ONE short plain update.
        "inputs": {
            "agent": "cfo",
            "mode": "shift_start",
            "report": (
                "Period spend = $41.20 vs $60.00 salary (69% burn). Anomaly: web_manual_tester "
                "$9.80 = 2.1x its $4.60 band. No money moved."
            ),
            "summary": "CFO scheduled shift digest.",
        },
        "outputs": {
            "expected": (
                "Exactly ONE short plain update (<=2 sentences): what spend looks like (~$41 of "
                "$60, ~69% burn), the one anomaly (web_manual_tester ~2x band), and the single "
                "thing needing Shay's decision if any. No emoji/markdown. Report-only."
            )
        },
        "metadata": {"suite": "exec", "agent": "cfo", "mode": "shift_start"},
    },
    {
        # Daily ops digest — fleet-wide aggregate report (real daily_digest shape).
        "inputs": {
            "agent": "daily_digest",
            "mode": "observe",
            "target": "scheduler fleet",
            "report": (
                "Fleet digest: revenue_reporter=(no digest yet); store_health=unverifiable "
                "(could not check store status — RevenueCat creds missing); git_sync_auditor=2 "
                "branches behind main; 23 agents clocked in, all report-only on probation."
            ),
            "summary": "Daily fleet digest stitched from per-agent local digests.",
        },
        "outputs": {
            "expected": (
                "A single fleet-wide digest that honestly leads with what's known and flags "
                "gaps as '(no digest yet)' / 'unverifiable — could not check store status' "
                "rather than inventing data; notes report-only posture. Concrete and grounded."
            )
        },
        "metadata": {"suite": "ops", "agent": "daily_digest"},
    },
    {
        # Store-health ops case — the honest "could not check store status" warning.
        "inputs": {
            "agent": "store_health_checker",
            "mode": "observe",
            "target": "scheduler RevenueCat offering",
            "report": (
                "Store health: products fetch failed (RevenueCat creds missing) -> emit one "
                "'unverifiable: could not check store status' warning. SKU purchasability could "
                "not be confirmed. Denylisted ids skipped."
            ),
            "summary": "Store-health check of the live offering.",
        },
        "outputs": {
            "expected": (
                "Emits exactly one honest 'unverifiable / could not check store status' warning "
                "when creds are missing (does NOT claim healthy and does NOT claim broken), "
                "names that SKU purchasability is unconfirmed, and skips denylisted ids."
            )
        },
        "metadata": {"suite": "ops", "agent": "store_health_checker"},
    },
]


# The full local seed: QA toy cases (kept stable) + real exec/ops cases.
EVAL_EXAMPLES: list[dict[str, Any]] = [*_QA_CASES, *_EXEC_OPS_CASES]


def example_count() -> int:
    return len(EVAL_EXAMPLES)
