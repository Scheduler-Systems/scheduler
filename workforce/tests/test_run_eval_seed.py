"""Tests for the dataset-GROWTH / seeding path (scripts/run_eval._seed_examples).

The runner's docstring promises seeding is IDEMPOTENT: "Add the eval examples to the
dataset IF it has none yet". These tests pin that contract:

  - a clean (empty) dataset is seeded exactly once with the full local seed;
  - an already-populated dataset is NOT re-seeded (no duplicates);
  - and — the bug this file exercises — when the idempotency LIST probe hits a
    transient error (exactly the "SDK hiccup / offline backend" condition the rest of
    this codebase is built to degrade SAFELY around), the seeder must NOT blindly
    re-insert every example into a dataset that may already be populated. Doing so
    creates DUPLICATE examples (LangSmith does not dedupe by input), which silently
    corrupts the eval dataset the redeploy gate scores against.

NO real network: the LangSmith client is a Mock.
Run: .venv/bin/python -m unittest tests.test_run_eval_seed -v
"""
import unittest
from unittest import mock

import scripts.run_eval as run_eval
from agent_toolkit.eval_dataset import EVAL_EXAMPLES


class SeedIdempotencyTests(unittest.TestCase):
    def test_seeds_empty_dataset_once(self):
        client = mock.Mock()
        client.list_examples.return_value = []  # dataset is empty
        client.create_examples.return_value = mock.Mock()

        added = run_eval._seed_examples(client, "ds-id")

        self.assertTrue(client.create_examples.called)
        self.assertEqual(added, len(EVAL_EXAMPLES))

    def test_does_not_reseed_already_populated_dataset(self):
        client = mock.Mock()
        # list returns a non-empty page -> dataset already has examples.
        client.list_examples.return_value = [mock.Mock()]

        added = run_eval._seed_examples(client, "ds-id")

        client.create_examples.assert_not_called()
        client.create_example.assert_not_called()
        self.assertEqual(added, 0)

    def test_transient_list_error_must_not_reinsert_duplicates(self):
        """A list-probe hiccup must degrade SAFELY, not duplicate the whole dataset.

        The idempotency probe (`client.list_examples`) can fail transiently — a 503, a
        permission blip, SDK drift — the same fail-safe conditions handled elsewhere.
        If that probe raises, the seeder currently falls through and unconditionally
        re-inserts ALL examples. Against an already-populated `scheduler-qa-eval`
        dataset that produces DUPLICATE examples, biasing the redeploy gate's aggregate
        toward whatever inputs got doubled. The seeder must NOT create examples when it
        could not confirm the dataset is empty.
        """
        client = mock.Mock()
        client.list_examples.side_effect = RuntimeError("transient 503 from LangSmith")
        client.create_examples.return_value = mock.Mock()

        run_eval._seed_examples(client, "already-populated-ds")

        # FAILS today: the seeder re-inserts every example after a list hiccup, which
        # duplicates an already-populated dataset.
        client.create_examples.assert_not_called()
        client.create_example.assert_not_called()


if __name__ == "__main__":
    unittest.main()
