"""Platform department — agents that own + maintain the LangSmith runtime itself.

Today (2026-06-06) I (Claude) hand-run the LangSmith provisioning / evals / crons. This
package is the BUILD-not-operate move: a deployed agent (Lennox, the AI/LangSmith Platform
Specialist) owns that loop — read-only + PROPOSE-ONLY, never auto-deploys / auto-changes config.
"""
