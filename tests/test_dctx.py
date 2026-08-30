# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""dctx -- the certified context artifact.

A receipt is only worth minting if it can FAIL. These tests attack the four ways
it could be a rubber stamp:

  * it verifies a fresh slice but does not notice the checkout moving underneath
    it (staleness);
  * its SHA drifts with the environment, so no two machines ever agree
    (determinism);
  * a planted credential either rides along inside the slice, or -- worse -- gets
    quoted into the certificate that claims its absence (egress);
  * it reports recall 1.0 when nobody supplied any labels, which is the vacuous
    number this whole artifact exists to refuse (anti-tautology).

All model-free, all offline.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from daedalus import dctx

# Real shape, fake bytes: an AWS access key id trips SECRET_FLOOR_CONTENT.
PLANTED_AKIA = "AKIAIOSFODNN7EXAMPLE"
FAKE_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEA0000000000000000000000000000000000000000000000\n"
    "-----END RSA PRIVATE KEY-----\n"
)

REPO = str(Path(__file__).resolve().parents[1])


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _fixture(root: Path) -> None:
    """A focus with one real callee, so the manifest has something to certify
    beyond the focus file itself."""
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/util.py", "def helper(x):\n    return x + 1\n")
    _write(root, "pkg/app.py",
           "from pkg.util import helper\n\n\n"
           "def dispatch(payload):\n    return helper(payload)\n")


class VerifyPredicateTest(unittest.TestCase):
    def test_verify_passes_on_a_freshly_compiled_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch")
            ok, failures = dctx.verify(receipt, root)
            self.assertTrue(ok, failures)
            self.assertEqual(failures, [])
            # The callee really is in the manifest -- otherwise this test would
            # pass vacuously on an empty slice.
            self.assertIn("pkg/util.py", {u["file"] for u in receipt["manifest"]["included"]})

    def test_verify_fails_with_a_specific_reason_after_an_edit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch")
            _write(root, "pkg/util.py", "def helper(x):\n    return x + 999\n")
            ok, failures = dctx.verify(receipt, root)
            self.assertFalse(ok)
            self.assertTrue(any("unit digest mismatch" in f and "pkg/util.py" in f
                                for f in failures), failures)

    def test_verify_fails_on_a_hand_edited_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch")
            receipt["manifest"]["withheld"] = []
            receipt["manifest"]["shell_boundary_stops"] = 0
            receipt["recall"] = 1.0
            ok, failures = dctx.verify(receipt, root)
            self.assertFalse(ok)
            self.assertTrue(any("receipt_sha does not match" in f for f in failures),
                            failures)

    def test_commit_absence_is_reported_not_omitted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch")
            self.assertIn("commit_sha", receipt)
            self.assertIn("commit_status", receipt)
            self.assertIn(receipt["commit_status"],
                          ("ok", "not_a_git_repo", "git_unavailable"))
            if receipt["commit_status"] != "ok":
                self.assertIsNone(receipt["commit_sha"])


class ReceiptHashBoundaryTest(unittest.TestCase):
    """The SHA must cover the structural claims and nothing environmental --
    otherwise the same commit certifies differently on two machines."""

    def test_tokenizer_and_environment_fields_are_out_of_the_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch")
            before = dctx._receipt_sha(receipt)
            receipt["tokens"]["slice_tokens"] += 4321
            receipt["tokens"]["whole_repo_tokens"] += 999
            receipt["tokens"]["whole_repo_tokens_exact"] = not receipt["tokens"]["whole_repo_tokens_exact"]
            receipt["tokens"]["reduction_pct"] = 0.0
            receipt["backend"] = "some-other-engine"
            receipt["manifest"]["included"][0]["tokens"] = 100000
            self.assertEqual(dctx._receipt_sha(receipt), before)

    def test_structural_fields_are_in_the_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch")
            before = dctx._receipt_sha(receipt)
            receipt["manifest"]["included"][0]["sha256"] = "0" * 64
            self.assertNotEqual(dctx._receipt_sha(receipt), before)

    def test_hashed_fields_is_derived_from_the_canonical_form(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch")
            self.assertEqual(receipt["hashed_fields"], sorted(dctx._canonical(receipt)))
            for excluded in ("tokens", "backend", "hashed_fields", "receipt_sha"):
                self.assertNotIn(excluded, receipt["hashed_fields"])


# The determinism probe runs in a SUBPROCESS: PYTHONHASHSEED is read at
# interpreter start, so an in-process loop cannot test what this needs to test.
_DETERMINISM_SNIPPET = r"""
import sys
sys.path.insert(0, {repo!r})
from daedalus import dctx
r = dctx.compile({root!r}, "pkg/app.py::dispatch")
print(r["receipt_sha"])
"""


class DeterminismTest(unittest.TestCase):
    def test_receipt_sha_is_identical_across_hash_seeds(self):
        """Set/dict iteration order has leaked into this repo's output before
        (graph resolution picks the FIRST import defining a name). A receipt SHA
        that moves with PYTHONHASHSEED certifies nothing, so the fixture is built
        with several modules exporting the same name to give order a chance to
        leak."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "pkg/__init__.py", "")
            for n in "abcdef":
                _write(root, f"pkg/mod_{n}.py",
                       f"def helper(x):\n    return 'FROM_MOD_{n.upper()}'\n")
            _write(root, "pkg/app.py",
                   "".join(f"from pkg.mod_{n} import helper as h_{n}\n" for n in "abcdef")
                   + "\n\ndef dispatch(payload):\n    return helper(payload)\n")

            code = _DETERMINISM_SNIPPET.format(repo=REPO, root=str(root))
            shas = {}
            for seed in ("0", "1", "12345", "99991", "31337"):
                env = dict(os.environ, PYTHONHASHSEED=seed)
                out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                     text=True, env=env, cwd=REPO)
                self.assertEqual(out.returncode, 0, out.stderr)
                shas[seed] = out.stdout.strip().splitlines()[-1]
            self.assertEqual(len(set(shas.values())), 1,
                             f"receipt_sha differs across PYTHONHASHSEED: {shas}")


class PlantedSecretTest(unittest.TestCase):
    def test_planted_credential_flips_the_receipt_and_never_appears_in_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            clean = dctx.compile(root, "pkg/app.py::dispatch")
            self.assertIn("pkg/util.py",
                          {u["file"] for u in clean["manifest"]["included"]})

            _write(root, "pkg/util.py",
                   f"AWS_ACCESS_KEY_ID = '{PLANTED_AKIA}'\n\n\n"
                   "def helper(x):\n    return x + 1\n")
            dirty = dctx.compile(root, "pkg/app.py::dispatch")

            self.assertNotEqual(dirty["receipt_sha"], clean["receipt_sha"])
            # The neighbour is now WITHHELD, and therefore no longer certified as
            # included: the gate moved it from one list to the other.
            self.assertIn("pkg/util.py",
                          {w["file"] for w in dirty["manifest"]["withheld"]})
            self.assertNotIn("pkg/util.py",
                             {u["file"] for u in dirty["manifest"]["included"]})
            # Nothing that IS included trips the floor -- the certificate's own
            # second opinion agrees with the slicer.
            self.assertTrue(dirty["egress_verdict"]["pass"],
                            dirty["egress_verdict"]["violations"])

            # A certificate that quoted the secret whose absence it certifies
            # would be a catastrophic own-goal. The rule NAME may appear; the
            # VALUE may not, anywhere, at any nesting depth.
            blob = json.dumps(dirty, sort_keys=True)
            self.assertNotIn(PLANTED_AKIA, blob)
            self.assertTrue(any("secret" in w["rule"] for w in dirty["manifest"]["withheld"]),
                            dirty["manifest"]["withheld"])

    def test_a_secret_planted_after_minting_fails_verification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch")
            _write(root, "pkg/util.py",
                   f"KEY = '''{FAKE_PEM}'''\n\n\ndef helper(x):\n    return x + 1\n")
            ok, failures = dctx.verify(receipt, root)
            self.assertFalse(ok)
            self.assertTrue(any(f.startswith("egress violation: pkg/util.py")
                                for f in failures), failures)
            self.assertFalse(any("BEGIN RSA PRIVATE KEY" in f for f in failures),
                             failures)


class AntiTautologyTest(unittest.TestCase):
    """The headline invariant: labels are an INPUT, never derived from the same
    walk that built the slice. eval/harness.py:_recall returns 1.0 for an empty
    label list; dctx must return null instead."""

    def test_no_labels_means_recall_is_null_and_never_one(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch")
            self.assertEqual(receipt["label_provenance"], "none")
            self.assertIsNone(receipt["recall"])
            self.assertNotEqual(receipt["recall"], 1.0)
            self.assertEqual(receipt["labels"], [])
            ok, failures = dctx.verify(receipt, root)
            self.assertTrue(ok, failures)

    def test_a_receipt_claiming_recall_without_labels_fails_verification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch")
            receipt["recall"] = 1.0
            receipt["receipt_sha"] = dctx._receipt_sha(receipt)   # re-seal the lie
            ok, failures = dctx.verify(receipt, root)
            self.assertFalse(ok)
            self.assertTrue(any("must be null" in f for f in failures), failures)

    def test_supplied_labels_are_scored_and_attributed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch",
                                   labels=["helper", "nonexistent_symbol"],
                                   label_provenance="independent_diff")
            self.assertEqual(receipt["label_provenance"], "independent_diff")
            self.assertEqual(receipt["recall"], 0.5)
            self.assertEqual(receipt["labels_found"], ["helper"])
            ok, failures = dctx.verify(receipt, root)
            self.assertTrue(ok, failures)

    def test_labels_without_a_provenance_are_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            with self.assertRaises(ValueError):
                dctx.compile(root, "pkg/app.py::dispatch", labels=["helper"])
            with self.assertRaises(ValueError):
                dctx.compile(root, "pkg/app.py::dispatch",
                             label_provenance="temporal_churn")
            with self.assertRaises(ValueError):
                dctx.compile(root, "pkg/app.py::dispatch", labels=["helper"],
                             label_provenance="vibes")

    def test_circular_provenance_is_recorded_not_silently_blessed(self):
        """hand_reachable labels ARE circular (the slicer chose what it is graded
        on). dctx records that so a consumer can segregate the number; it does
        not reject it, and it does not launder it into an unlabelled tier."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            receipt = dctx.compile(root, "pkg/app.py::dispatch", labels=["helper"],
                                   label_provenance="hand_reachable")
            self.assertEqual(receipt["label_provenance"], "hand_reachable")
            self.assertEqual(receipt["recall"], 1.0)
            self.assertIn("label_provenance", receipt["hashed_fields"])


if __name__ == "__main__":
    unittest.main()
