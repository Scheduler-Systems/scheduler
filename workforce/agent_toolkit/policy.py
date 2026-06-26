"""Anthropic-terms guard.

These agents do ORCHESTRATION ONLY — they call Claude/LLMs to coordinate work. They must
NEVER run, train, fine-tune, evaluate, or distill an ML model. This is enforced in shared
code (not trusted to prompts): any agent action whose target matches the model-development
boundary is hard-blocked.

See the workspace AGENTS.md: no AI/ML model development via Claude Code (incl. gal-model).

WHY THIS IS NOT A PLAIN SUBSTRING DENYLIST
------------------------------------------
A naive case-insensitive substring match over a handful of exact literal spellings fails OPEN
under trivial obfuscation: the SAME entity (gal-model) and the SAME operations (fine-tune,
distill, train) expressed with a dropped hyphen, an underscore, a space, or an ordinary synonym
("train", "pretrain", "LoRA", "RLHF", "SFT", "adapter") sail straight through. The eval/target
text Lennox (platform_specialist) routes through this guard is attacker-influenced (a compromised
prompt-under-test, a dataset/feedback row, or a Prompt-Hub system prompt), so a one-character edit
must not be able to bypass the SOLE code-level enforcement of a HARD Anthropic-terms gate.

So the guard NORMALIZES the target (lowercase, collapse hyphen/underscore/space, strip punctuation)
and TOKEN-matches an EXPANDED model-development vocabulary — an allow-listed set of operations and
entities — rather than enumerating literal bad spellings. The workspace lesson is explicit:
"allow-list + real-bool, never denylist/truthy-tuple" — the operations we BLOCK are an allow-list of
known model-development verbs/entities; anything that spells out one of them is refused.
"""
import re

# ---------------------------------------------------------------------------
# Back-compat: the original literal denylist is still exported (it is part of the
# public API / ``__all__``). It is the LOWER bound of what is blocked — the
# normalized/tokenized matching below is strictly stronger (it blocks everything
# these literals do, plus their punctuation/synonym variants).
# ---------------------------------------------------------------------------
MODEL_DEV_DENYLIST = (
    "gal-model",
    "governance/eval-worker",
    "eval-worker",
    "model-scoring",
    "model-training",
    "fine-tune",
    "distill",
)


# ---------------------------------------------------------------------------
# Normalization: lowercase, then collapse the separators that distinguish
# "gal-model" / "gal_model" / "gal model" / "galmodel" and "fine-tune" /
# "fine_tune" / "fine tune" / "finetune". Everything that is not a letter or a
# digit becomes a single space, AND a separator-free copy is produced so a
# token like "galmodel" (no separator at all) is also caught.
# ---------------------------------------------------------------------------
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize(target: str) -> tuple[str, str]:
    """Return (spaced, joined) normalized forms of ``target``.

    spaced: lowercased, every run of non-alphanumerics collapsed to one space.
            -> matches token / phrase patterns ("train ... model", "gal model").
    joined: spaced with ALL spaces removed.
            -> matches separator-free spellings ("galmodel", "finetune", "modeltraining").
    """
    low = (target or "").lower()
    spaced = _NON_ALNUM.sub(" ", low).strip()
    joined = spaced.replace(" ", "")
    return spaced, joined


# ---------------------------------------------------------------------------
# TIER A — unambiguous model-development tokens/entities. Their presence ALONE
# is model-development work; they never legitimately appear in QA/scheduling/
# revenue text. Matched against the separator-free ``joined`` form so that
# "gal-model", "gal_model", "gal model" and "galmodel" all collapse to the same
# thing. Word-style tokens (lora/rlhf/sft/distill/pretrain/finetune) are matched
# against ``spaced`` with word boundaries so they don't fire inside unrelated
# words.
# ---------------------------------------------------------------------------
# Entity / compound spellings, separator-free (checked as substrings of ``joined``):
_BLOCK_JOINED = (
    "galmodel",          # gal-model / gal_model / gal model / galmodel
    "evalworker",        # eval-worker / governance/eval-worker
    "modelscoring",      # model-scoring
    "modeltraining",     # model-training
    "modeldistillation",
)

# Standalone operation tokens (whole-word in ``spaced``). These are model-training/
# distillation operations that have no legitimate meaning in orchestration QA text.
_BLOCK_WORD = re.compile(
    r"\b("
    r"finetune|finetuning|finetuned|"
    r"distill|distills|distilled|distilling|distillation|"
    r"pretrain|pretrains|pretrained|pretraining|"
    r"lora|qlora|rlhf|dpo|ppo|"
    r"sft|"               # supervised fine-tuning
    r"backprop|backpropagation"
    r")\b"
)

# ---------------------------------------------------------------------------
# TIER B — a model-development VERB together with a model OBJECT. Either token on
# its own can appear in ordinary text ("the model summary", "training plan",
# "reward for the win"), so we only block when a training verb co-occurs with a
# model object. This catches "train a reward model", "fine tune the reward model",
# "compute gradients and update the model weights", "RLHF the classifier", etc.
# ---------------------------------------------------------------------------
_VERB = re.compile(
    r"\b("
    r"train|trains|trained|training|retrain|retrains|retrained|retraining|"
    r"fine\s+tune|fine\s+tunes|fine\s+tuned|fine\s+tuning|"
    r"rlhf|"
    r"gradient|gradients|backprop|"
    r"update[sd]?|optimiz[a-z]*|"        # "update the model weights", "optimize the weights"
    r"checkpoint|checkpoints"
    r")\b"
)
_OBJECT = re.compile(
    r"\b("
    r"model|models|"
    r"classifier|classifiers|"
    r"weights|"
    r"reward\s+model|reward\s+head|reward\s+function|"
    r"neural|transformer|embedding\s+model|"
    r"checkpoint"
    r")\b"
)


class ModelWorkBlocked(RuntimeError):
    pass


def _matched_reason(target: str) -> str | None:
    """Return a short reason string if ``target`` is model-development work, else None."""
    spaced, joined = _normalize(target)
    if not spaced:
        return None

    # Back-compat literals first (covers anything the originals covered verbatim).
    low = (target or "").lower()
    for bad in MODEL_DEV_DENYLIST:
        if bad in low:
            return f"denylist literal '{bad}'"

    # TIER A — entity / op token alone.
    for tok in _BLOCK_JOINED:
        if tok in joined:
            return f"model-dev entity '{tok}'"
    m = _BLOCK_WORD.search(spaced)
    if m:
        return f"model-dev operation '{m.group(1)}'"

    # TIER B — training verb co-occurring with a model object.
    verb = _VERB.search(spaced)
    obj = _OBJECT.search(spaced)
    if verb and obj:
        return f"model-dev operation '{verb.group(1)}' on '{obj.group(1)}'"

    return None


def assert_not_model_work(target: str) -> None:
    """Raise if `target` (a repo path, suite name, command, prompt, eval/target text, ...) touches
    model development. Fails CLOSED on the gal-model entity and on train/pretrain/finetune/distill/
    LoRA/RLHF/SFT operations regardless of punctuation or synonym — not just exact literal spellings."""
    reason = _matched_reason(target)
    if reason is not None:
        raise ModelWorkBlocked(
            f"Blocked: '{target}' matches the model-development boundary ({reason}). "
            "QA agents are orchestration-only per Anthropic terms — no train/eval/distill/serve."
        )
