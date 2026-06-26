#!/usr/bin/env bash
# Local git-maintainer runner — invoked by launchd (or by hand).
#
# Runs the graphs.local.git_local_maintainer graph ON this Mac (it needs the
# local filesystem), traced to the SAME LangSmith project as the deployed fleet.
#
# Config via env (all optional; sensible defaults):
#   GIT_MAINTAINER_REPO   path to the qa-agent-platform checkout (default: derived)
#   GIT_MAINTAINER_ENV    env file with LANGSMITH_API_KEY etc. (default: $REPO/.env)
#   WORKSPACE_ROOT        workspace to scan (default: the enterprise workspace)
#   GIT_MAINTAINER_DRY_RUN=1   report only, delete nothing
set -euo pipefail

REPO="${GIT_MAINTAINER_REPO:-/Users/scheduler-systems/Documents/scheduler-systems-ltd/Scheduler-Systems/qa-agent-platform}"
ENV_FILE="${GIT_MAINTAINER_ENV:-$REPO/.env}"
PY="$REPO/.venv/bin/python"
export WORKSPACE_ROOT="${WORKSPACE_ROOT:-/Users/scheduler-systems/Documents/scheduler-systems-ltd}"
export LANGSMITH_TRACING="${LANGSMITH_TRACING:-true}"

# Load LangSmith (and any other) credentials without echoing them.
if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; fi

LOG_DIR="$WORKSPACE_ROOT/.tmp/git-local-maintainer"
mkdir -p "$LOG_DIR"

cd "$REPO"
exec "$PY" -c "
from graphs.local import git_local_maintainer as m
out = m.graph.invoke({})
r = out.get('report', {})
print('git_local_maintainer:', r)
" >>"$LOG_DIR/run.log" 2>&1
