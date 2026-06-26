"""Run a CLOUD ops graph locally for a scheduled report — report-only by default.

Used by the launchd plists for revenue_reporter (weekly) and store_health_checker (daily)
until/unless these are scheduled on LangGraph Platform. Report-only delivery is the default
(set OPS_REPORT_ONLY=1 + GITHUB_OPS_REPORT_ONLY=1 in the plist) so an unattended run never
writes to GitHub and never blocks on an approval interrupt.

Usage: python scripts/run_ops_graph.py <graph_module>   # e.g. revenue_reporter, conversion_growth_analyst
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from importlib import import_module

# Cloud graphs live across graphs/ops (revenue_reporter, store_health_checker, daily_digest),
# graphs/marketing (the growth agents), graphs/exec (CFO/COO/CTO/CMO/CEO), and graphs/board
# (board_chair, audit_risk_director, growth_director).
_PACKAGES = ("graphs.ops", "graphs.marketing", "graphs.exec", "graphs.board")

mod_name = sys.argv[1] if len(sys.argv) > 1 else "revenue_reporter"
mod = None
for _pkg in _PACKAGES:
    try:
        mod = import_module(f"{_pkg}.{mod_name}")
        break
    except ModuleNotFoundError as exc:
        # Only swallow the "wrong package" miss; a real missing dependency must surface.
        if exc.name not in (f"{_pkg}.{mod_name}", _pkg):
            raise
        continue
if mod is None:
    raise SystemExit(f"graph module '{mod_name}' not found in {_PACKAGES}")
out = mod.graph.invoke({})
print(f"{mod_name}:", out.get("report", {}))
