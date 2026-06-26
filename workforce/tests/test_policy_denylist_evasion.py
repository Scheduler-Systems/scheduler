"""Anthropic-terms boundary — denylist EVASION tests for ``assert_not_model_work``.

``agent_toolkit/policy.py`` is the ONLY code-level enforcement of the Anthropic-terms
boundary for the whole fleet. Lennox (platform_specialist) — whose duties are eval-of-agent-
OUTPUT and agent-prompt engineering — routes EVERY judged/eval/target/prompt string through
``assert_not_model_work`` and its docstring promises it "FAILS CLOSED" so the fleet "never
trains/distills/serves a model" (graphs/platform/platform_specialist.py:27-31).

The guard is a SUBSTRING match over a tiny fixed denylist of exact literal terms
(``MODEL_DEV_DENYLIST``). That makes it fail-OPEN under trivial obfuscation: the SAME entities
and the SAME operations expressed with a dropped hyphen, an underscore, a space, or an ordinary
synonym ("train", "pretrain", "LoRA", "RLHF", "SFT", "adapter") are NOT blocked. A
compromised/misbehaving prompt-under-test (the eval target output is attacker-influenced — see
evaluations._guard_payload's own docstring) that emits "finetune the gal_model classifier" is
therefore NOT refused: it reaches the paid judge/model and is reported on as healthy QA — exactly
the "steer Lennox into gal-model / model-training work" hole the boundary is supposed to close.

These tests assert the BOUNDARY THE DOCSTRINGS PROMISE (block model-training/distillation/the
gal-model entity regardless of punctuation/synonym), so they FAIL against today's literal
denylist and will pass once the guard is hardened (normalize punctuation + cover the
train/pretrain/distill/LoRA/RLHF/SFT/adapter vocabulary, ideally tokenized not substring).

No network, no model, no creds — the policy module is imported directly by file path so it runs
in CI without the heavy ``agent_toolkit`` package deps (langchain_core et al.).

Run: .venv/bin/python -m unittest tests.test_policy_denylist_evasion -v
"""
import importlib.util
import os
import unittest

# Import agent_toolkit/policy.py in isolation (the package __init__ pulls langchain_core,
# which is intentionally absent in the creds-free CI eval path).
_POLICY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "agent_toolkit",
    "policy.py",
)
_spec = importlib.util.spec_from_file_location("agent_toolkit_policy_under_test", _POLICY_PATH)
policy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(policy)

assert_not_model_work = policy.assert_not_model_work
ModelWorkBlocked = policy.ModelWorkBlocked


class TestDenylistEvasion(unittest.TestCase):
    """The guard must FAIL CLOSED on model-training/distillation/gal-model however it is spelled."""

    def _assert_blocked(self, target: str):
        with self.assertRaises(
            ModelWorkBlocked,
            msg=(
                f"assert_not_model_work({target!r}) did NOT block — this is unambiguous "
                "AI/ML model-development work that the Anthropic-terms guard promises to "
                "FAIL CLOSED on, but the literal-substring denylist let it through."
            ),
        ):
            assert_not_model_work(target)

    # --- control: the canonical literal forms ARE blocked (guard is wired) ---------------
    def test_canonical_literals_block(self):
        for t in ("fine-tune the gal-model classifier", "distill the teacher",
                  "model-training run", "model-scoring pipeline"):
            with self.subTest(target=t):
                self._assert_blocked(t)

    # --- the gal-model ENTITY, punctuation-shifted (same repo, dodges the literal) -------
    def test_gal_model_entity_punctuation_variants_block(self):
        for t in ("finetune the gal_model classifier",     # underscore + no-hyphen finetune
                  "train galmodel from scratch",            # no separator
                  "gal model reward head eval"):            # space
            with self.subTest(target=t):
                self._assert_blocked(t)

    # --- the fine-tune OPERATION, punctuation-shifted ------------------------------------
    def test_finetune_operation_variants_block(self):
        for t in ("finetune the judge on agent logs",       # no hyphen
                  "fine tune the reward model"):             # space
            with self.subTest(target=t):
                self._assert_blocked(t)

    # --- ordinary model-TRAINING vocabulary the denylist never lists --------------------
    def test_training_vocabulary_blocks(self):
        for t in ("train a reward model on these labels",
                  "pretrain a classifier on agent outputs",
                  "run a LoRA adapter SFT on the judge model",
                  "RLHF the verdict classifier with these preferences",
                  "compute gradients and update the model weights"):
            with self.subTest(target=t):
                self._assert_blocked(t)


if __name__ == "__main__":
    unittest.main()
