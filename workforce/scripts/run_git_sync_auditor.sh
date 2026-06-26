#!/usr/bin/env bash
# git_sync_auditor runner — invoked by launchd (or by hand).
#
# Runs the graphs.ops.git_sync_auditor graph ON this Mac (it needs the local
# filesystem to see the multi-repo workspace), traced to the SAME LangSmith project
# as the deployed fleet. STRICTLY READ-ONLY: reports local<->remote divergence; it
# never pushes, fetches (by default), removes worktrees, or deletes branches.
#
# Config via env (all optional; sensible defaults):
#   GIT_SYNC_AUDITOR_ENV   env file with LANGSMITH_API_KEY etc. (default: $REPO/.env, then canonical)
#   WORKSPACE_ROOT         workspace to scan (default: the enterprise workspace)
#   GIT_SYNC_AUDITOR_FETCH=1   opt-in `fetch --prune` before auditing (default OFF — passive observer)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
ENV_FILE="${GIT_SYNC_AUDITOR_ENV:-$REPO/.env}"
if [ ! -f "$ENV_FILE" ]; then
  ENV_FILE="/Users/scheduler-systems/Documents/scheduler-systems-ltd/Scheduler-Systems/qa-agent-platform/.env"
fi
PY="$REPO/.venv/bin/python"
export WORKSPACE_ROOT="${WORKSPACE_ROOT:-/Users/scheduler-systems/Documents/scheduler-systems-ltd}"
export LANGSMITH_TRACING="${LANGSMITH_TRACING:-true}"

# Load LangSmith (and any other) credentials without echoing them.
if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; fi

LOG_DIR="$WORKSPACE_ROOT/.tmp/git-sync-auditor"
mkdir -p "$LOG_DIR"

cd "$REPO"
exec "$PY" -c "
from graphs.ops import git_sync_auditor as m
out = m.graph.invoke({})
print('git_sync_auditor:', out.get('report', {}))
" >>"$LOG_DIR/run.log" 2>&1
