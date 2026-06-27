"""Shared toolkit imported by every agent graph.

Build the cross-cutting seams ONCE here so each agent is just business logic:
- model routing (cost-first: DeepSeek default, Haiku/gpt-mini escalation)
- approval gate (the load-bearing human-in-the-loop primitive)
- OpenTelemetry instrumentation (fail-safe)
- GAL governance capture (fail-safe)
- remote-runner dispatch (heavy execution never runs in the agent container)
- Anthropic-terms guard (orchestration only; no model train/eval/distill)
- GCP credentials bootstrap (fail-safe — no interactive gcloud auth ever needed)
"""
# Bootstrap GCP credentials early so any graph that needs Firebase/GCP APIs
# finds GOOGLE_APPLICATION_CREDENTIALS already set.  Fail-safe: if no GCP
# credentials are available the call is a silent no-op and non-GCP agents
# are completely unaffected.
from .gcp_auth import ensure_gcp_credentials as _ensure_gcp_credentials
_ensure_gcp_credentials()

# NB: ``models`` and ``budget`` pull in langchain/langgraph, which are only present in the
# deployed (graph) environment. They are resolved LAZILY via ``__getattr__`` (PEP 562) below so
# that the deterministic, report-only consumers of this toolkit (e.g. ``github_ops``,
# ``pr_eval``) can ``import agent_toolkit`` with NO langchain/langgraph installed. Any graph
# that actually uses these names triggers the real import on first attribute access — exactly
# when it is running under langchain/langgraph anyway. The public API is unchanged.
from .approval import request_approval, is_approved
from .otel import span, get_tracer
from .governance import capture as governance_capture
from .dispatch import dispatch_github_workflow
from .policy import assert_not_model_work, ModelWorkBlocked, MODEL_DEV_DENYLIST
# Per-agent write-enable gate (graduate report-only → WRITE one agent at a time). Default-deny:
# everyone report-only until named on AGENTS_WRITE_ENABLED (and never a never-list agent).
from .write_gate import (
    write_enabled,
    report_only_for,
    never_listed,
    write_allowlist,
    global_report_only,
    TIER1_WRITE_ENABLED,
    TIER2_WRITE_ENABLED,
    HARD_NEVER_LIST,
)
# Ops-fleet shared seams (revenue/store reporting + reachability + digests).
from .http_probe import probe as http_probe
# Gmail seam (read + DRAFT only, NEVER send) for the email-triage agent. Imported as a module so
# tests can ``mock.patch.object(m.gmail_client, "is_configured", ...)`` exactly like revenuecat.
from . import gmail_client
from .ops_report import write_local_digest, file_digest_issue, file_digest_record, read_local_digest
# Lane discipline (each systemic item has ONE owner) + escalation framing (only bright-line
# items address the founder). Defined ONCE so the policy cannot drift per agent.
from .lanes import (
    SYSTEMIC_ITEMS,
    systemic_item_for,
    owns_systemic_item,
    may_report,
    filter_owned,
    see_owner_pointer,
    is_bright_line,
    founder_ask_count,
    frame_escalation,
    addressee,
)
# Slack posting — fail-safe; no-op when SLACK_BOT_TOKEN/SLACK_WEBHOOK_URL are absent.
from .slack_tool import post_digest as slack_post, ensure_channels as slack_ensure_channels

__all__ = [
    "get_model",
    "TIER_DEFAULT",
    "TIER_COMPLEX",
    "TIER_BROWSER",
    "TIER_COMPUTER_USE",
    "request_approval",
    "is_approved",
    "span",
    "get_tracer",
    "governance_capture",
    "dispatch_github_workflow",
    "assert_not_model_work",
    "ModelWorkBlocked",
    "MODEL_DEV_DENYLIST",
    "budget_guard",
    "check_clocked_in",
    # per-agent write-enable gate (graduation)
    "write_enabled",
    "report_only_for",
    "never_listed",
    "write_allowlist",
    "global_report_only",
    "TIER1_WRITE_ENABLED",
    "TIER2_WRITE_ENABLED",
    "HARD_NEVER_LIST",
    # ops fleet
    "http_probe",
    "gmail_client",
    "write_local_digest",
    "file_digest_issue",
    "file_digest_record",
    "read_local_digest",
    # lane discipline + escalation framing
    "SYSTEMIC_ITEMS",
    "systemic_item_for",
    "owns_systemic_item",
    "may_report",
    "filter_owned",
    "see_owner_pointer",
    "is_bright_line",
    "founder_ask_count",
    "frame_escalation",
    "addressee",
    # slack
    "slack_post",
    "slack_ensure_channels",
    # gcp auth bootstrap (called at import time; also exportable for explicit use)
    "ensure_gcp_credentials",
]

# Re-export for explicit callers
from .gcp_auth import ensure_gcp_credentials  # noqa: E402 F401


# --- Lazy (langchain/langgraph-backed) symbols ------------------------------------------
# Resolved on first access so the package imports without those deps (see the note above the
# ``approval`` import). Maps each public name to the (submodule, attr) that provides it.
_LAZY_ATTRS = {
    "get_model": ("models", "get_model"),
    "TIER_DEFAULT": ("models", "TIER_DEFAULT"),
    "TIER_COMPLEX": ("models", "TIER_COMPLEX"),
    "TIER_BROWSER": ("models", "TIER_BROWSER"),
    "TIER_COMPUTER_USE": ("models", "TIER_COMPUTER_USE"),
    "budget_guard": ("budget", "budget_guard"),
    "check_clocked_in": ("budget", "check_clocked_in"),
}


def __getattr__(name: str):  # PEP 562 module-level lazy attribute access
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    mod = importlib.import_module(f".{target[0]}", __name__)
    return getattr(mod, target[1])
