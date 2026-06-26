#!/usr/bin/env bash
# memory_sync runner — invoked by launchd (or by hand).
#
# Runs the graphs.ops.memory_sync graph ON this Mac (it needs the local memory stores),
# traced to the SAME LangSmith project as the deployed fleet. PROBATION = DRY-RUN: it
# reports what WOULD sync and uploads NOTHING. Credential files / secret-pattern records
# are excluded (never uploaded). Arm a real backend only after sign-off (see ops-fleet.md).
#
# Config via env (all optional):
#   MEMORY_SYNC_BACKEND   dryrun|langgraph_store|litestream|claude_memory_git (default: dryrun)
#   MEMORY_SYNC_APPLY=1   actually run the backend (default UNSET => dry-run, uploads nothing)
#   MEMORY_SYNC_ENV       env file (default: $REPO/.env, then canonical)
#   WORKSPACE_ROOT        workspace root (default: the enterprise workspace)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
ENV_FILE="${MEMORY_SYNC_ENV:-$REPO/.env}"
if [ ! -f "$ENV_FILE" ]; then
  ENV_FILE="/Users/scheduler-systems/Documents/scheduler-systems-ltd/Scheduler-Systems/qa-agent-platform/.env"
fi
PY="$REPO/.venv/bin/python"
export WORKSPACE_ROOT="${WORKSPACE_ROOT:-/Users/scheduler-systems/Documents/scheduler-systems-ltd}"
export LANGSMITH_TRACING="${LANGSMITH_TRACING:-true}"
export MEMORY_SYNC_BACKEND="${MEMORY_SYNC_BACKEND:-dryrun}"
# NOTE: MEMORY_SYNC_APPLY intentionally NOT set here => probation dry-run.

if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; fi

LOG_DIR="$WORKSPACE_ROOT/.tmp/memory-sync"
mkdir -p "$LOG_DIR"

cd "$REPO"
exec "$PY" -c "
from graphs.ops import memory_sync as m
out = m.graph.invoke({})
print('memory_sync:', out.get('report', {}))
" >>"$LOG_DIR/run.log" 2>&1
