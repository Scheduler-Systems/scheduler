"""Anthropic-terms guard.

These agents do ORCHESTRATION ONLY — they call Claude/LLMs to coordinate work. They must
NEVER run, train, fine-tune, evaluate, or distill an ML model. This is enforced in shared
code (not trusted to prompts): any agent action whose target matches the model-development
denylist is hard-blocked.

See the workspace AGENTS.md: no AI/ML model development via Claude Code (incl. gal-model).
"""

MODEL_DEV_DENYLIST = (
    "gal-model",
    "governance/eval-worker",
    "eval-worker",
    "model-scoring",
    "model-training",
    "fine-tune",
    "distill",
)


class ModelWorkBlocked(RuntimeError):
    pass


def assert_not_model_work(target: str) -> None:
    """Raise if `target` (a repo path, suite name, command, ...) touches model development."""
    low = (target or "").lower()
    for bad in MODEL_DEV_DENYLIST:
        if bad in low:
            raise ModelWorkBlocked(
                f"Blocked: '{target}' matches the model-development denylist ('{bad}'). "
                "QA agents are orchestration-only per Anthropic terms — no train/eval/distill."
            )
