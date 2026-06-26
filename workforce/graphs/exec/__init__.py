"""Executive suite — monitoring/proposal officers over their domains (propose-only).

Executives CONSUME the other agents' reports (local digests + LangSmith traces + roster/payroll)
rather than re-doing work, and land every action as a PROPOSAL in the digest:
  - cfo  — monitors ALL spend (token burn vs salaries, API/infra cost, revenue-vs-cost); the
           budget hard-caps are its enforcement lever; proposes budget allocation to hr_ops_manager.
  - coo  — ops fleet health: schedules firing, the launchd/substrate failures, maintainers.
  - cto  — repo/deploy/security posture (e.g. the held IDOR rollout), PR/CI state.
  - cmo  — growth agents' output + the RC funnel.
  - ceo  — synthesizes the exec reports into company priorities; chairs the proposal queue.
Shay is founder + investor; the CEO proposes, Shay ratifies. All probation/report-only.
"""
