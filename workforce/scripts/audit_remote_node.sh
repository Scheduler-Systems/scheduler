#!/usr/bin/env bash
# Node git-state audit (issue #3): SSH to a (mobile/ephemeral) Stratus node and report
# every repo holding work that isn't backed up — uncommitted, unpushed, stashed, or in
# extra worktrees. These nodes (mac-pro-1, kali-1) are reimaged/roam, so local-only work
# is at risk. READ-ONLY: this never modifies the remote.
#
# Usage: scripts/audit_remote_node.sh <ssh-host-or-ip>   [max_idle_days_unused]
# Example: scripts/audit_remote_node.sh 100.104.121.114        # mac-pro-1 over Tailscale
#
# Exit: prints noteworthy repos; excludes ephemeral sandboxes (.gal-test, caches).
set -euo pipefail
HOST="${1:?usage: audit_remote_node.sh <ssh-host-or-ip>}"

# Harden against SSH option/config injection: a HOST starting with '-' could be parsed
# as an ssh flag (e.g. -oProxyCommand=...) → local RCE. Reject hostile values, restrict to
# a hostname/IPv4/IPv6 charset, and pass '--' so ssh stops option parsing.
case "$HOST" in
  -*) echo "refusing host starting with '-' (option-injection)" >&2; exit 2 ;;
esac
if ! printf '%s' "$HOST" | grep -qE '^[A-Za-z0-9._:-]+$'; then
  echo "refusing host with unexpected characters: '$HOST'" >&2; exit 2
fi

ssh -o ConnectTimeout=8 -o BatchMode=yes -- "$HOST" 'bash -s' <<'REMOTE'
repos=$(find "$HOME" -maxdepth 6 -name .git \( -type d -o -type f \) -prune 2>/dev/null \
  | sed "s#/.git\$##" \
  | grep -vE "/\.gal-test/|/\.claude/|/\.codex/|/node_modules/|/\.cache/|/Library/|/\.cargo/|/\.rustup/|/go/pkg/")
total=0; note=0
echo "host=$(hostname)  scanned_root=$HOME"
echo "=== repos with uncommitted / unpushed / stashed / multi-worktree work ==="
for r in $repos; do
  total=$((total+1))
  cd "$r" 2>/dev/null || continue
  dirty=$(git status --porcelain 2>/dev/null | wc -l | tr -d " ")
  branch=$(git branch --show-current 2>/dev/null)
  ahead=$(git rev-list --count "@{u}..HEAD" 2>/dev/null || echo 0)
  stash=$(git stash list 2>/dev/null | wc -l | tr -d " ")
  wt=$(git worktree list 2>/dev/null | wc -l | tr -d " ")
  if [ "$dirty" != "0" ] || [ "$ahead" != "0" ] || [ "$stash" != "0" ] || [ "$wt" -gt 1 ]; then
    note=$((note+1))
    echo "• ${r/#$HOME/\~}  [${branch:-DETACHED}] dirty=$dirty ahead=$ahead stash=$stash worktrees=$wt"
  fi
done
echo ""
echo "SUMMARY: real repos scanned=$total | noteworthy=$note | (.gal-test sandboxes excluded)"
REMOTE
