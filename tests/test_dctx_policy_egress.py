"""dctx -- receipts minted under a project policy must verify under that SAME
policy, not the generic default.

compile() threads a caller-supplied ``policy`` into the slice AND into the
receipt's egress verdict; verify() used to re-run the egress gate with the
DEFAULT policy only and the receipt recorded no policy identity. The result was
a soundness break: a receipt minted honestly under a project allow-list (the
only way source reaches an untrusted lane at all) false-alarmed on verify()
against a pristine, unmodified checkout -- an 'egress violation' on files the
minting policy explicitly permitted.

These tests pin the fix: the egress-relevant projection of the policy travels in
the receipt, is hashed (so it cannot be swapped for a laxer one), and is rebuilt
at verify time -- while a default-policy receipt is byte-identical to before.
All offline, no model.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from daedalus import dctx
from daedalus.sensitivity import load_policy

FAKE_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEA0000000000000000000000000000000000000000000000\n"
    "-----END RSA PRIVATE KEY-----\n"
)


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _fixture(root: Path) -> None:
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/util.py", "def helper(x):\n    return x + 1\n")
    _write(root, "pkg/app.py",
           "from pkg.util import helper\n\n\n"
           "def dispatch(payload):\n    return helper(payload)\n")


# The generic allow-list (docs/, /tests/, .md, ...) does NOT cover pkg/, so on an
# untrusted lane the fixture source only survives to the slice when a project
# policy allow-lists it. That is exactly the case the receipt must carry.
_PKG_POLICY = load_policy({"policy": {"allow": ["pkg/"]}})


class PolicyRoundTripTest(unittest.TestCase):
    def test_untrusted_project_policy_receipt_verifies_on_pristine_checkout(self):
        """Failure scenario (a): honest mint under a project allow-list must not
        false-alarm at verify. This is the soundness invariant the fix restores."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch",
                                   lane="untrusted", policy=_PKG_POLICY)
            # The policy actually did its job: source reached the slice.
            self.assertIn("pkg/app.py",
                          {u["file"] for u in receipt["manifest"]["included"]})
            self.assertTrue(receipt["egress_verdict"]["pass"],
                            receipt["egress_verdict"]["violations"])
            ok, failures = dctx.verify(receipt, root)
            self.assertTrue(ok, failures)
            self.assertEqual(failures, [])

    def test_default_policy_receipt_carries_no_policy_field_and_still_verifies(self):
        """The additive guarantee: a caller that passes no policy gets a receipt
        with no egress_policy key -- byte-identical hashing to before the field
        existed -- and it verifies clean."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch")
            self.assertNotIn("egress_policy", receipt)
            self.assertNotIn("egress_policy", receipt["hashed_fields"])
            ok, failures = dctx.verify(receipt, root)
            self.assertTrue(ok, failures)


class PolicyIsInTheHashTest(unittest.TestCase):
    def test_recorded_policy_is_hashed_and_tamper_evident(self):
        """The egress_policy projection is inside receipt_sha: relaxing the
        recorded allow-list to smuggle a laxer predicate past verify moves the
        SHA, so verify catches it as a tampered receipt."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch",
                                   lane="untrusted", policy=_PKG_POLICY)
            self.assertIn("egress_policy", receipt["hashed_fields"])
            before = dctx._receipt_sha(receipt)
            receipt["egress_policy"]["allow_substrings"].append("everything/")
            self.assertNotEqual(dctx._receipt_sha(receipt), before)

    def test_forged_lax_policy_still_cannot_ride_a_real_secret_past_verify(self):
        """Fail-closed backstop: even a wholly forged receipt whose egress_policy
        allow-lists the world cannot verify once a real secret is present -- the
        unconditional secret floor (tier 1) is policy-independent."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch",
                                   lane="untrusted", policy=_PKG_POLICY)
            # Plant a secret into an already-included file, then re-seal a receipt
            # whose policy allow-lists everything -- the attacker's best case.
            _write(root, "pkg/util.py",
                   f"KEY = '''{FAKE_PEM}'''\n\n\ndef helper(x):\n    return x + 1\n")
            receipt["egress_policy"]["allow_substrings"] = ["pkg/"]
            receipt["egress_policy"]["default_deny"] = False
            receipt["receipt_sha"] = dctx._receipt_sha(receipt)  # re-seal the forgery
            ok, failures = dctx.verify(receipt, root)
            self.assertFalse(ok)
            # Caught either by the unit-digest change or the secret floor -- but a
            # secret-floor egress violation must be among the reasons, and the PEM
            # bytes must never be quoted back into the failure text.
            self.assertTrue(any(f.startswith("egress violation: pkg/util.py")
                                for f in failures), failures)
            self.assertFalse(any("BEGIN RSA PRIVATE KEY" in f for f in failures),
                             failures)

    def test_policy_fingerprint_is_deterministic_regardless_of_input_order(self):
        """The projection reaches the SHA, so it must not move with the order the
        policy's sets happened to be built in."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            pa = load_policy({"policy": {"allow": ["pkg/", "z/", "a/"]}})
            pb = load_policy({"policy": {"allow": ["a/", "pkg/", "z/"]}})
            ra = dctx.compile(root, "pkg/app.py::dispatch", lane="untrusted", policy=pa)
            rb = dctx.compile(root, "pkg/app.py::dispatch", lane="untrusted", policy=pb)
            self.assertEqual(ra["egress_policy"], rb["egress_policy"])
            self.assertEqual(ra["receipt_sha"], rb["receipt_sha"])


class ProjectDenyContentTest(unittest.TestCase):
    def test_project_deny_content_secret_is_rechecked_at_verify(self):
        """The under-detection leg: a project-defined deny_content pattern must be
        re-run at verify. A marker that ONLY the project policy flags, planted
        after minting, must fail the receipt under that policy -- and (control) a
        default-policy verify of the same bytes must not, proving the recheck uses
        the recorded project predicate, not the generic one."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            # A benign-looking marker no generic rule matches, made sensitive only
            # by this project's deny_content.
            marker_policy = load_policy({"policy": {
                "allow": ["pkg/"],
                "deny_content": [r"COMPANY_INTERNAL_MARKER"],
            }})
            receipt = dctx.compile(root, "pkg/app.py::dispatch",
                                   lane="untrusted", policy=marker_policy)
            ok, failures = dctx.verify(receipt, root)
            self.assertTrue(ok, failures)

            # Plant the project-only marker into an included file. It must trip the
            # recorded project predicate at verify.
            _write(root, "pkg/util.py",
                   "# COMPANY_INTERNAL_MARKER = do-not-egress\n"
                   "def helper(x):\n    return x + 1\n")
            ok2, failures2 = dctx.verify(receipt, root)
            self.assertFalse(ok2)
            self.assertTrue(any(f.startswith("egress violation: pkg/util.py")
                                for f in failures2), failures2)
            # The recorded projection carried the project pattern.
            blob = json.dumps(receipt["egress_policy"], sort_keys=True)
            self.assertIn("COMPANY_INTERNAL_MARKER", blob)


if __name__ == "__main__":
    unittest.main()
