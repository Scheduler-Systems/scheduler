"""Shared toolkit imported by every agent graph.

Build the cross-cutting seams ONCE here so each agent is just business logic:
- model routing (cost-first: DeepSeek default, Haiku/gpt-mini escalation)
- approval gate (the load-bearing human-in-the-loop primitive)
- OpenTelemetry instrumentation (fail-safe)
- GAL governance capture (fail-safe)
- remote-runner dispatch (heavy execution never runs in the agent container)
- Anthropic-terms guard (orchestration only; no model train/eval/distill)
"""
from .models import (
    get_model,
    TIER_DEFAULT,
    TIER_COMPLEX,
    TIER_BROWSER,
    TIER_COMPUTER_USE,
)
from .approval import request_approval, is_approved
from .otel import span, get_tracer
from .governance import capture as governance_capture
from .dispatch import dispatch_github_workflow
from .policy import assert_not_model_work, ModelWorkBlocked, MODEL_DEV_DENYLIST
from .budget import budget_guard, check_clocked_in

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
]
