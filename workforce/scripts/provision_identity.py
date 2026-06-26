#!/usr/bin/env python3
"""provision_identity — turn a roster row into a per-agent least-privilege identity.

WHY (constitution §3 + AGENTS.md per-agent-identity rail): every deployed agent must
authenticate AS ITSELF — its own Vault AppRole + scoped policy + k8s ServiceAccount,
least-privilege per its roster role. NO shared credentials (per-agent audit +
blast-radius containment). The spec existed (governance/constitution.md §3,
StratusCloudLabs/.../vault/VAULT-ACCESS.md §6) with NO code behind it — agents currently
share the cluster's ESO read path. This script is that missing code.

WHAT IT DOES: for each rostered+deployed agent it reads its `privilege_class` (from
roster.yaml), looks the class up in governance/privilege-classes.yaml, and GENERATES the
exact per-agent artifacts:
  * a Vault policy HCL — read-only on ONLY that agent's scoped paths (+ the class's shared
    read paths). One agent can never read another's secrets (isolation, proven by tests).
  * an AppRole definition — the agent's own Vault identity (token_policies = its policy).
  * a k8s ServiceAccount — the agent's pod identity in `gal-agents`.
  * a SecretStore + ExternalSecret — wires the AppRole → the pod's env, scoped to its subtree.
  * an APPLY PLAN — the exact `vault` / `kubectl` commands an operator (or the ops-provisioner
    agent, post-bootstrap) runs to apply them.

THE GATE (why this never touches prod itself): applying a Vault policy / AppRole is a
security-baseline prod change = HARD GATE (founder sign-off). So this script, like
VAULT-ACCESS.md, produces *reviewable artifacts + a runbook* — it does NOT shell out to
vault/kubectl. `--apply` only PRINTS the plan (and refuses without the explicit env ack).
After the one-time root bootstrap (see scripts/bootstrap_fleet.sh + docs/ops/FLEET-BRINGUP.md),
the ops-provisioner agent runs the plan for every other agent — the founder grants once, not
per-agent. Minting a class NOT in the registry is impossible here (fail-closed) — that's the
"new privilege class = escalate" boundary, enforced in code.

FAIL-CLOSED: an agent with no `privilege_class` defaults to the most restrictive class
(`read-only`) and is flagged for explicit HR assignment. An agent referencing a class NOT in
the registry is an ERROR (exit 1) — we never invent or widen access.

Usage:
    python -m scripts.provision_identity                 # dry-run ALL deployed agents → out/
    python -m scripts.provision_identity --agent cfo     # just one
    python -m scripts.provision_identity --check         # CI lint: every agent maps to a known
                                                         #   class; fail closed on unknown. names only.
    python -m scripts.provision_identity --check --json  # machine-readable coverage report
    python -m scripts.provision_identity --apply         # PRINT the apply plan (still operator-run);
                                                         #   refuses unless FLEET_BRINGUP_APPLY=1

Exit codes: 0 OK · 1 a referenced class is unknown / coverage failed · 2 bad usage.
This script is READ-ONLY w.r.t. the cluster and NEVER prints a secret VALUE (only PATHS).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROSTER = ROOT / "roster.yaml"
CLASSES = ROOT / "governance" / "privilege-classes.yaml"
LANGGRAPH = ROOT / "langgraph.json"
OUT_DIR = ROOT / "out" / "identities"


# --- loading -----------------------------------------------------------------------------
def load_registry() -> dict:
    return yaml.safe_load(CLASSES.read_text())


def load_roster() -> dict:
    return yaml.safe_load(ROSTER.read_text()).get("agents") or {}


def deployed_graphs() -> set[str]:
    return set(json.loads(LANGGRAPH.read_text())["graphs"])


# --- the pure core (unit-tested; no Vault/k8s/network) -----------------------------------
class UnknownClassError(ValueError):
    """A roster row references a privilege_class that is not in the closed registry."""


def resolve_class(agent: str, row: dict, registry: dict) -> tuple[str, bool]:
    """Return (class_name, used_default). Fail-closed: missing → default; unknown → raise."""
    classes = registry["classes"]
    default = registry["meta"]["default_class"]
    requested = (row or {}).get("privilege_class")
    if requested is None:
        return default, True
    if requested not in classes:
        raise UnknownClassError(
            f"agent {agent!r} requests privilege_class {requested!r}, which is NOT in "
            f"governance/privilege-classes.yaml. A new/widened class is a security-baseline "
            f"change (founder gate) — add it there first. Known: {sorted(classes)}"
        )
    return requested, False


def agent_secret_glob(registry: dict, agent: str) -> str:
    return f"{registry['meta']['agent_secret_root']}/{agent}/*"


def vault_policy_hcl(agent: str, class_name: str, registry: dict) -> str:
    """Least-privilege HCL: read ONLY this agent's subtree + the class's shared read paths.

    Isolation invariant (tested): the ONLY agent-scoped path is THIS agent's — never another's.
    No `create`/`update`/`delete`/`sudo` capability is ever emitted (Vault writes stay closed).
    """
    cls = registry["classes"][class_name]
    paths = [agent_secret_glob(registry, agent), *cls.get("extra_vault_read", [])]
    # The shared model-key + telemetry paths every agent needs to run + emit traces.
    shared = registry["meta"]["shared_secret_root"]
    paths += [f"{shared}/model-keys", f"{shared}/langfuse-ingest"]
    # de-dup, stable order
    seen: list[str] = []
    for p in paths:
        if p not in seen:
            seen.append(p)
    blocks = "\n".join(
        f'path "{p}" {{\n  capabilities = ["read"]\n}}' for p in seen
    )
    header = (
        f"# AUTO-GENERATED by scripts/provision_identity.py — DO NOT hand-edit.\n"
        f"# Per-agent Vault policy for {agent!r} (class: {class_name}). READ-ONLY, scoped.\n"
    )
    return header + blocks + "\n"


def approle_plan(agent: str, class_name: str, registry: dict) -> dict:
    """The AppRole spec for this agent's own Vault identity. Short-lived tokens, its policy only."""
    policy = f"agent-{agent}"
    return {
        "role_name": f"agent-{agent}",
        "token_policies": [policy],
        "token_ttl": "20m",          # short-lived: a leaked token expires fast
        "token_max_ttl": "1h",
        "secret_id_ttl": "24h",       # rotate the secret-id daily
        "secret_id_num_uses": 0,       # unlimited within ttl (one pod, many shifts)
        "token_num_uses": 0,
        "_class": class_name,
    }


def k8s_service_account(agent: str, registry: dict) -> dict:
    ns = registry["meta"]["k8s_namespace"]
    return {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {
            "name": f"agent-{agent}",
            "namespace": ns,
            "labels": {"app.kubernetes.io/part-of": "agent-fleet", "fleet/agent": agent},
            "annotations": {
                "fleet/provisioned-by": "scripts/provision_identity.py",
                "fleet/privilege-class": "set-by-provisioner",
            },
        },
        "imagePullSecrets": [{"name": "ghcr-secret"}],
    }


def external_secret(agent: str, class_name: str, registry: dict) -> list[dict]:
    """A per-agent SecretStore (AppRole-auth) + ExternalSecret scoped to this agent's subtree.

    ESO authenticates to Vault with THIS agent's AppRole and can therefore only materialize the
    secrets its policy permits — the scope is enforced by Vault, not just by the manifest.
    """
    ns = registry["meta"]["k8s_namespace"]
    mount = registry["meta"]["vault_kv_mount"]
    # data path WITHOUT the KV-v2 `data/` infix — ESO's `path` is the logical KV path.
    agent_path = f"gal-run/agents/{agent}"
    store = {
        "apiVersion": "external-secrets.io/v1beta1",
        "kind": "SecretStore",
        "metadata": {"name": f"agent-{agent}-vault", "namespace": ns},
        "spec": {
            "provider": {
                "vault": {
                    "server": "http://vault.vault.svc.cluster.local:8200",
                    "path": mount,
                    "version": "v2",
                    "auth": {
                        "appRole": {
                            "path": "approle",
                            "roleId": f"<role_id for agent-{agent} — from AppRole>",
                            "secretRef": {
                                "name": f"agent-{agent}-approle-secret-id",
                                "key": "secret-id",
                            },
                        }
                    },
                }
            }
        },
    }
    es = {
        "apiVersion": "external-secrets.io/v1beta1",
        "kind": "ExternalSecret",
        "metadata": {"name": f"agent-{agent}-secrets", "namespace": ns},
        "spec": {
            "refreshInterval": "1h",
            "secretStoreRef": {"name": f"agent-{agent}-vault", "kind": "SecretStore"},
            "target": {"name": f"agent-{agent}-env"},
            "dataFrom": [{"find": {"path": agent_path}}],
        },
    }
    return [store, es]


def apply_plan(agent: str, class_name: str, registry: dict) -> list[str]:
    """The exact operator commands to apply this identity. PRINTED, never executed here."""
    base = f"out/identities/{agent}"
    return [
        f"# --- agent {agent} (class: {class_name}) ---",
        f"vault policy write agent-{agent} {base}/policy.hcl",
        (
            f"vault write auth/approle/role/agent-{agent} "
            f"token_policies=agent-{agent} token_ttl=20m token_max_ttl=1h secret_id_ttl=24h"
        ),
        f"kubectl apply -f {base}/service-account.yaml",
        f"kubectl apply -f {base}/external-secret.yaml",
        (
            f"# then bind the AppRole role-id/secret-id into "
            f"secret agent-{agent}-approle-secret-id (operator, no plaintext on screen)"
        ),
    ]


def build_artifacts(agent: str, row: dict, registry: dict) -> dict:
    class_name, used_default = resolve_class(agent, row, registry)
    sa = k8s_service_account(agent, registry)
    sa["metadata"]["annotations"]["fleet/privilege-class"] = class_name
    return {
        "agent": agent,
        "class": class_name,
        "used_default": used_default,
        "policy.hcl": vault_policy_hcl(agent, class_name, registry),
        "approle.json": json.dumps(approle_plan(agent, class_name, registry), indent=2) + "\n",
        "service-account.yaml": yaml.safe_dump(sa, sort_keys=False),
        "external-secret.yaml": "---\n".join(
            yaml.safe_dump(d, sort_keys=False) for d in external_secret(agent, class_name, registry)
        ),
        "apply-plan.sh": "\n".join(apply_plan(agent, class_name, registry)) + "\n",
    }


# --- CLI ---------------------------------------------------------------------------------
def _targets(only: str | None) -> list[str]:
    roster = load_roster()
    graphs = deployed_graphs()
    names = sorted(n for n in roster if n in graphs)  # only DEPLOYED + rostered agents
    if only:
        if only not in roster:
            print(f"❌ {only!r} is not in roster.yaml", file=sys.stderr)
            sys.exit(2)
        names = [only]
    return names


def cmd_check(as_json: bool) -> int:
    """CI lint: every deployed+rostered agent maps to a KNOWN class. Fail closed on unknown."""
    registry = load_registry()
    roster = load_roster()
    rows = {n: roster[n] for n in _targets(None)}
    unknown, defaulted, ok = [], [], {}
    for agent, row in rows.items():
        try:
            cls, used_default = resolve_class(agent, row, registry)
        except UnknownClassError as e:
            unknown.append((agent, str(e)))
            continue
        ok[agent] = cls
        if used_default:
            defaulted.append(agent)
    if as_json:
        print(json.dumps(
            {"ok": ok, "defaulted_to_floor": defaulted,
             "unknown_class": [a for a, _ in unknown]}, indent=2))
    else:
        print(f"identity coverage: {len(ok)}/{len(rows)} deployed agents map to a known class.")
        for agent, cls in sorted(ok.items()):
            tag = "  (DEFAULT floor — assign explicitly)" if agent in defaulted else ""
            print(f"   - {agent}: {cls}{tag}")
        if defaulted:
            print(f"\n⏳ {len(defaulted)} agent(s) on the default floor ({registry['meta']['default_class']}); "
                  f"add an explicit `privilege_class:` to their roster row when HR assigns one.")
        for agent, msg in unknown:
            print(f"\n❌ {msg}")
    return 1 if unknown else 0


def cmd_generate(only: str | None) -> int:
    registry = load_registry()
    roster = load_roster()
    names = _targets(only)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wrote, defaulted = [], []
    for agent in names:
        try:
            arts = build_artifacts(agent, roster.get(agent) or {}, registry)
        except UnknownClassError as e:
            print(f"❌ {e}", file=sys.stderr)
            return 1
        d = OUT_DIR / agent
        d.mkdir(parents=True, exist_ok=True)
        for fname in ("policy.hcl", "approle.json", "service-account.yaml",
                      "external-secret.yaml", "apply-plan.sh"):
            (d / fname).write_text(arts[fname])
        wrote.append((agent, arts["class"]))
        if arts["used_default"]:
            defaulted.append(agent)
    print(f"✅ generated per-agent identity artifacts for {len(wrote)} agent(s) → {OUT_DIR.relative_to(ROOT)}/")
    for agent, cls in wrote:
        print(f"   - {agent}: {cls}")
    if defaulted:
        print(f"\n⏳ {len(defaulted)} on the default floor: {', '.join(defaulted)}")
    print("\nNOTE: artifacts are REVIEWABLE, not applied. Applying = security-baseline prod "
          "change (founder gate). Run with --apply to print the operator command plan.")
    return 0


def cmd_apply(only: str | None) -> int:
    import os
    if os.environ.get("FLEET_BRINGUP_APPLY") != "1":
        print("⛔ --apply only PRINTS the operator command plan; it does not run vault/kubectl.\n"
              "   Applying per-agent Vault policies/AppRoles is a HARD GATE (security baseline →\n"
              "   founder sign-off). Re-run with FLEET_BRINGUP_APPLY=1 to print the plan, then an\n"
              "   operator (or the ops-provisioner agent, post-bootstrap) runs it.", file=sys.stderr)
        return 2
    registry = load_registry()
    roster = load_roster()
    print("# OPERATOR APPLY PLAN — review, then run by hand (or via the ops-provisioner agent).")
    print("# Prereq: the one-time root bootstrap in scripts/bootstrap_fleet.sh is done.\n")
    for agent in _targets(only):
        cls, _ = resolve_class(agent, roster.get(agent) or {}, registry)
        print("\n".join(apply_plan(agent, cls, registry)))
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Provision per-agent least-privilege identities from the roster.")
    p.add_argument("--agent", help="only this agent (default: all deployed+rostered)")
    p.add_argument("--check", action="store_true", help="CI lint: every agent maps to a known class")
    p.add_argument("--apply", action="store_true", help="print the operator apply plan (needs FLEET_BRINGUP_APPLY=1)")
    p.add_argument("--json", action="store_true", help="machine-readable (with --check)")
    args = p.parse_args(argv)
    if args.check:
        return cmd_check(args.json)
    if args.apply:
        return cmd_apply(args.agent)
    return cmd_generate(args.agent)


if __name__ == "__main__":
    sys.exit(main())
