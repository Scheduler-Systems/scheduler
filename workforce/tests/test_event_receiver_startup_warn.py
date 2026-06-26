"""FINDING 2 — event_receiver logs a clear STARTUP warning when a webhook secret is unset.

Without a webhook secret the receiver 401s EVERY request for that source and only logs a coarse
per-request "rejected" line — so "nothing fires" is indistinguishable from "no traffic" (a SILENT
fail). The receiver must surface the misconfiguration LOUDLY at construction, naming ONLY the
unset var(s), never any value. These tests assert that startup warning + that it is silent when
configured + that the value is never logged.
"""
from __future__ import annotations

import logging
import os
import unittest
from unittest import mock

from scripts import event_receiver as er

_GH_VAL = "ghs_DO_NOT_LOG_THIS_VALUE"
_SENTRY_VAL = "sntry_DO_NOT_LOG_THIS_VALUE"


class StartupWarnsOnUnsetSecret(unittest.TestCase):
    def test_both_unset_logs_error_naming_both(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             self.assertLogs(er.logger, level="WARNING") as cm:
            rec = er.EventReceiver()  # warn_on_unset defaults True
            unset = rec.warn_unset_secrets()  # also returns the names
        joined = "\n".join(cm.output)
        self.assertIn("GITHUB_WEBHOOK_SECRET", joined)
        self.assertIn("SENTRY_CLIENT_SECRET", joined)
        self.assertEqual(set(unset), {"GITHUB_WEBHOOK_SECRET", "SENTRY_CLIENT_SECRET"})

    def test_only_github_unset_warns_about_github(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             self.assertLogs(er.logger, level="WARNING") as cm:
            er.EventReceiver(sentry_secret=_SENTRY_VAL)  # github unset
        joined = "\n".join(cm.output)
        self.assertIn("GITHUB_WEBHOOK_SECRET", joined)
        self.assertNotIn("SENTRY_CLIENT_SECRET", joined)  # sentry IS set ⇒ not named as unset

    def test_only_sentry_unset_warns_about_sentry(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             self.assertLogs(er.logger, level="WARNING") as cm:
            er.EventReceiver(github_secret=_GH_VAL)  # sentry unset
        joined = "\n".join(cm.output)
        self.assertIn("SENTRY_CLIENT_SECRET", joined)

    def test_no_warning_when_both_configured(self):
        # assertNoLogs is the inverse — both set ⇒ NO warning at construction.
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AssertionError):
                with self.assertLogs(er.logger, level="WARNING"):
                    er.EventReceiver(github_secret=_GH_VAL, sentry_secret=_SENTRY_VAL)

    def test_secret_value_is_never_logged(self):
        with mock.patch.dict(os.environ,
                             {"GITHUB_WEBHOOK_SECRET": _GH_VAL}, clear=True), \
             self.assertLogs(er.logger, level="WARNING") as cm:
            # sentry unset ⇒ warns; the SET github value must NOT appear anywhere in the log.
            er.EventReceiver()
        joined = "\n".join(cm.output)
        self.assertNotIn(_GH_VAL, joined)
        self.assertNotIn(_SENTRY_VAL, joined)

    def test_warn_on_unset_false_silences_for_tests(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AssertionError):
                with self.assertLogs(er.logger, level="WARNING"):
                    er.EventReceiver(warn_on_unset=False)

    def test_build_receiver_from_env_warns(self):
        # The deployment entry path (build_receiver_from_env → EventReceiver()) must also warn.
        with mock.patch.dict(os.environ, {}, clear=True), \
             self.assertLogs(er.logger, level="WARNING") as cm:
            er.build_receiver_from_env()
        self.assertIn("GITHUB_WEBHOOK_SECRET", "\n".join(cm.output))


if __name__ == "__main__":
    unittest.main()
