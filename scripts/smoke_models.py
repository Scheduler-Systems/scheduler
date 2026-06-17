"""Smoke-test the cost-first model routing.

Prints which provider/model each capability tier resolves to, given the keys in your env.
Run: python scripts/smoke_models.py    (pass --ping to do a 1-token live call per tier)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_toolkit.models import (  # noqa: E402
    get_model,
    TIER_DEFAULT,
    TIER_COMPLEX,
    TIER_BROWSER,
    TIER_COMPUTER_USE,
)

PING = "--ping" in sys.argv

for tier in (TIER_DEFAULT, TIER_COMPLEX, TIER_BROWSER, TIER_COMPUTER_USE):
    try:
        m = get_model(tier)
        name = getattr(m, "model", None) or getattr(m, "model_name", "?")
        line = f"{tier:13s} -> {type(m).__name__} ({name})"
        if PING:
            resp = m.invoke("reply with the single word: ok")
            line += f"  ping={getattr(resp, 'content', resp)!r}"
        print(line)
    except Exception as e:  # noqa: BLE001
        print(f"{tier:13s} -> NOT CONFIGURED: {e}")
