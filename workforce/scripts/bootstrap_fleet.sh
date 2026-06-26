#!/usr/bin/env bash
# =============================================================================
# bootstrap_fleet.sh — THE ONE root grant. Run ONCE by the founder/operator.
#
# WHY THIS EXISTS: a from-zero agent cannot mint its own first production credential
# (root-of-trust bootstrap). Everything else self-provisions — but SOMEONE has to seed the
# root of trust once. This script is that single action, made explicit, idempotent, and safe,
# so "flip the fleet live" is one reviewed yes instead of a pile of imperative kubectl/vault
# commands that a cluster rebuild silently loses (the exact gap VAULT-ACCESS.md §1/§5 flags).
#
# WHAT IT GRANTS (the irreducible founder bootstrap — a HARD GATE, security baseline):
#   1. Vault Kubernetes auth + the `eso-reader` read policy, bound to the ESO ServiceAccount
#      → so External-Secrets can deliver secrets to pods (the read side).
#   2. The scoped `gal-run-writer` policy + a named operator auth method (NOT root, NOT an agent)
#      → so secrets can be WRITTEN least-privilege (today writes are root-only — the gap).
#   3. A checklist of the Vault paths the fleet reads (NAMES ONLY — you paste the values
#      directly into `vault kv put`; this script never sees or prints a secret value).
# After that, NOTHING here is needed again: the ops-provisioner agent runs
# `scripts/provision_identity.py` to mint every agent's own identity (constitution §3), and
# ArgoCD reconciles the agent workloads. See docs/ops/FLEET-BRINGUP.md.
#
# SAFETY: DRY-RUN BY DEFAULT — it prints the plan and changes nothing. `--apply` runs the
# privileged commands and is intended for a human operator with a Vault admin login + kube
# context; it asks for an explicit typed confirmation first. This script does NOT deploy the
# fleet and does NOT write any secret value; applying it is a founder-gated security-baseline
# action. Re-running is safe (every step is idempotent / checked-before-create).
#
# Usage:
#   scripts/bootstrap_fleet.sh                 # DRY RUN — print the exact plan, change nothing
#   scripts/bootstrap_fleet.sh --apply         # operator: run it (asks to confirm; needs VAULT_ADDR + kube ctx)
#   scripts/bootstrap_fleet.sh --seed-checklist# just print the Vault paths to populate (names only)
# =============================================================================
set -euo pipefail

APPLY=0
SEED_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --seed-checklist) SEED_ONLY=1 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown arg: $arg (see --help)" >&2; exit 2 ;;
  esac
done

# The ESO identity + Vault facts (from StratusCloudLabs/.../workloads/vault/VAULT-ACCESS.md).
ESO_NAMESPACE="external-secrets"
ESO_SA="external-secrets"
ESO_ROLE="eso-reader"
WRITER_POLICY="gal-run-writer"
VAULT_KV_MOUNT="secret"
# Canonical policy HCL lives in the stratus GitOps repo; reference it, don't duplicate it.
STRATUS_VAULT_DIR="StratusCloudLabs/argocdgitops/clusters/stratus/workloads/vault"

say() { printf '%s\n' "$*"; }
run() {
  # echo the command; only execute it under --apply.
  say "  \$ $*"
  if [ "$APPLY" = "1" ]; then "$@"; fi
}

print_seed_checklist() {
  cat <<EOF
# ---- Vault paths the fleet READS (populate each ONCE; values come from YOU, never this script) ----
# Shared, read-only material every agent needs:
  vault kv put ${VAULT_KV_MOUNT}/gal-run/shared/model-keys        deepseek=…  gemini=…  anthropic=…
  vault kv put ${VAULT_KV_MOUNT}/gal-run/shared/langfuse-ingest   public-key=…  secret-key=…  host=…
# Class-scoped shared material (only the agents whose class needs it can read these):
  vault kv put ${VAULT_KV_MOUNT}/gal-run/shared/github-app-draft  app-id=…  installation-id=…  private-key=@key.pem   # repo-contributor
  vault kv put ${VAULT_KV_MOUNT}/gal-run/shared/billing-readonly  stripe-read=…  revenuecat-read=…                    # finance-reader
  vault kv put ${VAULT_KV_MOUNT}/gal-run/shared/audit-sink        url=…  token=…                                       # governance-auditor
  vault kv put ${VAULT_KV_MOUNT}/gal-run/shared/approle-bootstrap role-id-path=auth/approle                            # ops-provisioner
# Per-agent secrets (ONLY for agents that need their own, e.g. email_triage's Gmail token):
  vault kv put ${VAULT_KV_MOUNT}/gal-run/agents/email_triage/gmail  refresh-token=…  client-id=…  client-secret=…
# NOTE: 'vault kv put' REPLACES a whole path — use 'vault kv patch' to rotate ONE field
# (the langfuse/12-field footgun from VAULT-ACCESS.md). Never echo a value to your shell history.
EOF
}

if [ "$SEED_ONLY" = "1" ]; then print_seed_checklist; exit 0; fi

say "=============================================================================="
if [ "$APPLY" = "1" ]; then
  say " bootstrap_fleet.sh — APPLY MODE (privileged). This is a HARD GATE (security baseline)."
  say " Prereqs: a Vault ADMIN login (VAULT_ADDR set, e.g. via 'kubectl -n vault port-forward')"
  say "          and a kube context with cluster-admin on the target cluster."
  printf ' Type EXACTLY "bootstrap the fleet root of trust" to proceed: '
  read -r CONFIRM
  if [ "$CONFIRM" != "bootstrap the fleet root of trust" ]; then
    say " aborted — no changes made."; exit 1
  fi
  : "${VAULT_ADDR:?VAULT_ADDR must be set (point at the port-forwarded Vault)}"
else
  say " bootstrap_fleet.sh — DRY RUN. Nothing below is executed. Re-run with --apply (operator)."
fi
say "=============================================================================="

say ""
say "STEP 1/4 — Vault read side: Kubernetes auth + eso-reader → ESO can deliver secrets to pods."
run vault auth enable -path=kubernetes kubernetes || true   # idempotent: already-enabled is fine
say "  # write the read-only policy (read on ${VAULT_KV_MOUNT}/data/* ) and bind the ESO SA:"
run vault policy write "${ESO_ROLE}" "${STRATUS_VAULT_DIR}/policies/${ESO_ROLE}.hcl"
run vault write "auth/kubernetes/role/${ESO_ROLE}" \
  bound_service_account_names="${ESO_SA}" \
  bound_service_account_namespaces="${ESO_NAMESPACE}" \
  policies="${ESO_ROLE}" ttl=1h

say ""
say "STEP 2/4 — Vault write side: scoped ${WRITER_POLICY} (NOT root) + a named operator auth method."
run vault policy write "${WRITER_POLICY}" "${STRATUS_VAULT_DIR}/policies/${WRITER_POLICY}.hcl"
say "  # then enable ONE operator auth method mapped to ${WRITER_POLICY} (OIDC preferred):"
say "  #   vault auth enable oidc && vault write auth/oidc/role/operator token_policies=${WRITER_POLICY} …"
say "  # (left to the operator — ties to your IdP; do not create shared passwords.)"

say ""
say "STEP 3/4 — Seed the Vault paths the fleet reads (values come from you; never printed here):"
print_seed_checklist | sed 's/^/  /'

say ""
say "STEP 4/4 — Hand off to self-provisioning (NO further founder action):"
say "  # the ops-provisioner agent (security_officer) mints every agent's own identity:"
say "  \$ python -m scripts.provision_identity            # generate per-agent artifacts"
say "  \$ FLEET_BRINGUP_APPLY=1 python -m scripts.provision_identity --apply   # print the per-agent apply plan"
say "  # then ArgoCD reconciles the agent workloads (gal-agents) from the GitOps repo."
say ""
if [ "$APPLY" = "1" ]; then
  say "✅ root of trust bootstrapped. Per-agent self-provisioning + ArgoCD take it from here."
else
  say "ℹ️  DRY RUN complete — reviewed, nothing changed. The above is the ENTIRE founder bootstrap."
fi
