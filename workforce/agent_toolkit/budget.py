"""Budget-enforcement layer — wires the payroll "salaries" into the live model calls.

Where `payroll.py` is the HR ledger (what each agent's salary is, what it has spent,
whether it is over budget), THIS module is the enforcement seam that the agent graphs
actually call:

- ``load_budget_policy`` exposes the roster's team/per-run ceilings + each agent's salary.
- ``BudgetCallback`` is a LangChain callback that meters real token usage off every LLM
  response and records the spend against the agent's salary via ``payroll.record_spend``.
- ``check_clocked_in`` is the per-run gate an agent calls BEFORE working: it returns False
  (the agent must STOP) when the global kill-switch is set or the agent is over budget.
- ``budget_guard`` returns a model (via ``models.get_model``) with the metering callback
  attached and output tokens capped to the per-run ceiling where the provider supports it.

LOAD-BEARING RULE: every function here is FAIL-SAFE. A budget/telemetry problem must NEVER
crash an agent run — on any error we degrade to "let the agent keep working" (and, for the
model, fall back to a plain ``get_model``). The ledger/kill-switch are the real guardrails;
this layer only meters and caps best-effort.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel

from . import payroll
from .models import TIER_DEFAULT, get_model

# Env var that, when truthy, stops ALL agents immediately (mirrors
# roster.yaml -> policy.global_kill_switch_env). Kept as a constant so the gate is
# self-contained even if the roster can't be read.
KILL_SWITCH_ENV = "AGENTS_DISABLED"


def load_budget_policy() -> dict:
    """Return the budget knobs from roster.yaml (via payroll.load_roster). FAIL-SAFE.

    Returns a dict::

        {
          "team_token_budget":   int | None,   # total tokens/period for the QA team
          "per_run_token_ceiling": int | None, # hard kill-switch per single agent run
          "budget_period":       str | None,   # "weekly" | "monthly"
          "salary_tokens_per_week": {agent: int, ...},  # per-agent salary
        }

    Never raises: a missing/corrupt roster degrades to empty/None values.
    """
    policy: dict = {}
    salaries: dict[str, int] = {}
    try:
        roster = payroll.load_roster()
        policy = roster.get("policy", {}) or {}
        for name, record in (roster.get("agents", {}) or {}).items():
            value = (record or {}).get("salary_tokens_per_week")
            try:
                salaries[name] = int(value)
            except (TypeError, ValueError):
                continue
    except Exception:
        pass  # fail-safe: never break a run because the roster can't be read

    def _int_or_none(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return {
        "team_token_budget": _int_or_none(policy.get("team_token_budget")),
        "per_run_token_ceiling": _int_or_none(policy.get("per_run_token_ceiling")),
        "budget_period": policy.get("budget_period"),
        "salary_tokens_per_week": salaries,
    }


def _estimate_tokens_from_response(response: Any) -> int:
    """Best-effort token count for one LLM response. Returns 0 if nothing usable.

    Tries, in order:
      1) usage_metadata on the message generations (LangChain's normalized shape),
      2) llm_output["token_usage"] / ["usage"] (provider raw shape),
      3) a rough char/4 estimate over the generated text.
    Never raises.
    """
    # 1) Normalized usage_metadata on each generation's message.
    try:
        total = 0
        found = False
        for gen_list in getattr(response, "generations", []) or []:
            for gen in gen_list or []:
                message = getattr(gen, "message", None)
                usage = getattr(message, "usage_metadata", None) if message else None
                if isinstance(usage, dict):
                    tokens = usage.get("total_tokens")
                    if tokens is None:
                        tokens = (usage.get("input_tokens") or 0) + (
                            usage.get("output_tokens") or 0
                        )
                    if tokens:
                        total += int(tokens)
                        found = True
        if found:
            return total
    except Exception:
        pass

    # 2) Provider raw token_usage on llm_output.
    try:
        llm_output = getattr(response, "llm_output", None) or {}
        usage = (
            llm_output.get("token_usage")
            or llm_output.get("usage")
            or {}
        )
        if isinstance(usage, dict):
            tokens = usage.get("total_tokens")
            if tokens is None:
                tokens = (
                    (usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
                    + (usage.get("completion_tokens") or usage.get("output_tokens") or 0)
                )
            if tokens:
                return int(tokens)
    except Exception:
        pass

    # 3) Rough fallback: ~4 chars/token over the generated text.
    try:
        chars = 0
        for gen_list in getattr(response, "generations", []) or []:
            for gen in gen_list or []:
                text = getattr(gen, "text", None)
                if text is None:
                    message = getattr(gen, "message", None)
                    text = getattr(message, "content", "") if message else ""
                chars += len(text or "")
        if chars:
            return max(1, chars // 4)
    except Exception:
        pass

    return 0


class BudgetCallback(BaseCallbackHandler):
    """LangChain callback that meters token spend per agent against its salary.

    Attach to a model so every LLM response records its tokens via
    ``payroll.record_spend(agent, tokens)`` and accumulates a per-run total
    (``self.run_tokens``). FAIL-SAFE: ``on_llm_end`` NEVER raises.
    """

    def __init__(self, agent: str):
        self.agent = agent
        self.run_tokens = 0

    def on_llm_end(self, response: Any, **kw: Any) -> None:
        try:
            tokens = _estimate_tokens_from_response(response)
            if tokens <= 0:
                return
            self.run_tokens += tokens
            try:
                payroll.record_spend(self.agent, tokens)
            except Exception:
                pass  # ledger write failure must not crash the run
        except Exception:
            pass  # belt-and-suspenders: a callback must never break the model call


def check_clocked_in(agent: str) -> bool:
    """Return True if ``agent`` may work, False if it must STOP. FAIL-SAFE.

    The agent must STOP (returns False) when EITHER:
      - the global kill-switch env (AGENTS_DISABLED) is truthy, OR
      - the agent is over budget per the payroll ledger.

    Any error reading the ledger degrades to True (let the agent keep working) — the
    kill-switch env is the always-available hard stop.
    """
    if os.environ.get(KILL_SWITCH_ENV):
        return False
    try:
        if payroll.is_over_budget(agent):
            return False
    except Exception:
        return True  # fail-safe: a ledger/roster error must not silently halt the fleet
    return True


def budget_guard(
    agent: str, tier: str = TIER_DEFAULT, *, temperature: float = 0.0
) -> BaseChatModel:
    """Return a metered, output-capped model for ``agent`` at ``tier``. FAIL-SAFE.

    - Attaches a ``BudgetCallback`` so every LLM call records spend against the agent's
      salary (via ``.with_config(callbacks=[...])`` where supported).
    - Caps output tokens to ~``policy.per_run_token_ceiling`` where the provider exposes a
      ``max_output_tokens``/``max_tokens`` binding.
    - On ANY error, degrades to a plain ``get_model(tier, temperature=...)``.
    """
    try:
        model = get_model(tier, temperature=temperature)
    except Exception:
        # get_model itself failed — re-raise is the only honest option (no model to return),
        # but that's a configuration error surfaced by get_model, not a budget failure.
        raise

    # Best-effort output cap from the per-run ceiling.
    try:
        ceiling = load_budget_policy().get("per_run_token_ceiling")
        if ceiling:
            model = _cap_output_tokens(model, int(ceiling))
    except Exception:
        pass  # fail-safe: keep the uncapped model rather than crash

    # Attach the metering callback.
    try:
        callback = BudgetCallback(agent)
        if hasattr(model, "with_config"):
            return model.with_config(callbacks=[callback])
        return model
    except Exception:
        # Couldn't attach the callback — return the (possibly capped) plain model.
        return model


def _cap_output_tokens(model: BaseChatModel, ceiling: int) -> BaseChatModel:
    """Bind a max-output-tokens cap on providers that support one. Best-effort.

    Different LangChain integrations name the field differently
    (``max_output_tokens`` for Gemini, ``max_tokens`` for Anthropic/OpenAI/DeepSeek).
    We pick the one the model already declares so we never inject an unknown kwarg.
    Returns the original model unchanged if neither is supported.
    """
    cap = max(1, int(ceiling))
    for field in ("max_output_tokens", "max_tokens"):
        try:
            if hasattr(model, field) and hasattr(model, "bind"):
                return model.bind(**{field: cap})
        except Exception:
            continue
    return model
