"""The declared remote-Ollama lane.

``providers/ollama.py`` refuses to send repository content to any endpoint
that is not this machine, because "ollama" is a NAME and ``OLLAMA_HOST`` is
where the bytes actually go -- a distinction ``sensitivity.lane_for_host``
exists to keep, after exporting an RTX bench's address silently turned a
no-egress lane into a network one.

Consent re-opens that door for exactly one named endpoint. These tests pin
the two properties that make it safe: consent is per-host and exact, and it
grants USE of the lane without ever making the lane trusted -- so the
default-deny allow-list and the secret floor keep running over everything
sent to the bench.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from daedalus.providers import ollama as O

REMOTE = "http://100.119.126.9:11434"


def _provider(host: str, consent: str | None):
    env = {"OLLAMA_HOST": host}
    if consent is not None:
        env[O.REMOTE_CONSENT_VAR] = consent
    else:
        env.pop(O.REMOTE_CONSENT_VAR, None)
    with mock.patch.dict(os.environ, env, clear=False):
        if consent is None:
            os.environ.pop(O.REMOTE_CONSENT_VAR, None)
        provider = O.OllamaProvider()
        yield provider


class RefusalStandsByDefault(unittest.TestCase):
    def test_a_remote_host_without_consent_is_refused(self):
        for p in _provider(REMOTE, None):
            refusal = p._refuse_if_remote()
            self.assertIsNotNone(refusal)
            self.assertEqual(refusal["refused"], "remote_ollama_endpoint")
            self.assertEqual(refusal["host"], REMOTE)

    def test_loopback_needs_no_consent(self):
        for p in _provider("http://127.0.0.1:11434", None):
            self.assertIsNone(p._refuse_if_remote())


class ConsentIsPerHostAndExact(unittest.TestCase):
    def test_naming_this_host_permits_it(self):
        for p in _provider(REMOTE, REMOTE):
            self.assertIsNone(p._refuse_if_remote())

    def test_a_trailing_slash_is_the_same_endpoint(self):
        for p in _provider(REMOTE, REMOTE + "/"):
            self.assertIsNone(p._refuse_if_remote())

    def test_consent_for_another_host_does_not_transfer(self):
        # Repointing OLLAMA_HOST must silently REVOKE consent, not inherit it.
        for p in _provider("http://10.0.0.5:11434", REMOTE):
            self.assertIsNotNone(p._refuse_if_remote())

    def test_a_boolean_is_not_consent(self):
        # The variable holds a host. "1" would be consent to every endpoint
        # forever, including one a later config change substitutes.
        for value in ("1", "true", "yes", "*"):
            for p in _provider(REMOTE, value):
                self.assertIsNotNone(
                    p._refuse_if_remote(),
                    f"{value!r} must not read as consent to {REMOTE}",
                )

    def test_blank_consent_is_no_consent(self):
        for p in _provider(REMOTE, "   "):
            self.assertIsNotNone(p._refuse_if_remote())


class ConsentDoesNotGrantTrust(unittest.TestCase):
    def test_the_lane_stays_untrusted_even_when_consented(self):
        # THE WHOLE POINT. If consent flipped the lane to "trusted", the
        # default-deny allow-list in slice_egress_rule would switch OFF and
        # only the secret floor would remain -- reintroducing exactly the bug
        # lane_for_host was written to prevent.
        for p in _provider(REMOTE, REMOTE):
            self.assertIsNone(p._refuse_if_remote())
            self.assertEqual(p.egress_lane, "untrusted")

    def test_loopback_is_still_trusted(self):
        for p in _provider("http://127.0.0.1:11434", None):
            self.assertEqual(p.egress_lane, "trusted")


if __name__ == "__main__":
    unittest.main()
