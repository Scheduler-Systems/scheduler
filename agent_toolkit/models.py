"""Model routing for the agent fleet — cost-first.

Preference order (per Shay): DeepSeek for the cheap default; Claude Haiku 4.5 / OpenAI
gpt-mini for browser automation, computer use, and complex tasks. Until those keys are
added, the fleet bootstraps on the **GEMINI_API_KEY already in GCP Secret Manager**
(Gemini Flash = cheap default, Gemini Pro = escalation) — zero new signups.

Resolution per tier (first available wins):
  default tier     ->  DeepSeek  ->  Gemini Flash  ->  escalation
  escalation tier  ->  Anthropic Haiku / OpenAI gpt-mini  ->  Gemini Pro  ->  DeepSeek

Agent -> tier mapping (applied when each graph is built):
  automation engineers + qa_lead_aggregator  -> TIER_DEFAULT
  web/android/ios manual testers              -> TIER_BROWSER / TIER_COMPUTER_USE

NOTE: orchestration config (which LLM the agents *call*) — NOT model development.
"""
import os
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel

TIER_DEFAULT = "default"
TIER_COMPLEX = "complex"
TIER_BROWSER = "browser"
TIER_COMPUTER_USE = "computer_use"

_ESCALATION_TIERS = {TIER_COMPLEX, TIER_BROWSER, TIER_COMPUTER_USE}


def get_model(tier: str = TIER_DEFAULT, *, temperature: float = 0.0) -> BaseChatModel:
    """Return the chat model for a capability tier, with graceful provider fallback."""
    if tier in _ESCALATION_TIERS:
        return (
            _escalation(temperature)
            or _gemini(os.environ.get("GEMINI_PRO_MODEL", "gemini-2.5-pro"), temperature)
            or _deepseek(temperature)
            or _require()
        )
    return (
        _deepseek(temperature)
        or _gemini(os.environ.get("GEMINI_FLASH_MODEL", "gemini-2.5-flash"), temperature)
        or _escalation(temperature)
        or _require()
    )


def _deepseek(temperature: float) -> Optional[BaseChatModel]:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        return None
    from langchain_deepseek import ChatDeepSeek

    return ChatDeepSeek(model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"), temperature=temperature)


def _gemini(model: str, temperature: float) -> Optional[BaseChatModel]:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        return None
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(model=model, temperature=temperature, google_api_key=key)


def _escalation(temperature: float) -> Optional[BaseChatModel]:
    provider = os.environ.get("ESCALATION_PROVIDER", "anthropic").lower()
    if provider == "openai" and os.environ.get("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"), temperature=temperature)
    if os.environ.get("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5"), temperature=temperature)
    if os.environ.get("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"), temperature=temperature)
    return None


def _require() -> BaseChatModel:
    raise RuntimeError(
        "No model API key configured. Set one of DEEPSEEK_API_KEY / GEMINI_API_KEY "
        "(default tier) or ANTHROPIC_API_KEY / OPENAI_API_KEY (escalation) in .env."
    )
