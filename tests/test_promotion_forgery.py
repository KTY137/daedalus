"""Promotion could be forged two ways. These are the two, plus their controls.

FOUND BY AUDIT, 2026-07-29, against `daedalus/spine/bootstrap.py`. Both holes
were in `gate_discrimination`, the one function standing between a candidate
patch and a human being told "this may be promoted".

1. THE REVISION CLAUSE FAILED OPEN. The staleness test read
   `if head and measured_head and not head.startswith(measured_head)`, so a
   falsy `head` skipped it entirely. `shadow_run` resolves HEAD inside a bare
   `except Exception` that yields None, so a repository whose `.git` could not
   be read turned a receipt from ANY revision into `proven=True`. The
   function's own docstring claimed "measured against THE CURRENT REVISION"
   while `picker._head_sha`'s docstring said callers "fail OPEN on" None. Two
   documents, one code path, opposite claims -- and the code implemented the
   permissive one.

2. NO SANITY BOUND ON THE COUNTS. `{"planted": 12, "killed": 99}` produced a
   kill rate of 825%, which clears an 80% floor comfortably.

Each test below has a CONTROL that must stay green, because a refusal test
with no control proves only that the function can say no.

DELIBERATELY NOT COVERED, and the gap is named in the function's docstring:
the receipt has no integrity protection. Anything that can write
`runs/spine/` can author a receipt naming the current HEAD. That is a
key-management decision, not something a test can close.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from daedalus.spine import bootstrap as B

REAL_SHA = "a5fc7ce99731000000000000000000000000beef"
OTHER_SHA = "1234567890abcdef00000000000000000000cafe"


def _frozen_gate(head: str, gate_paths: tuple = ()) -> dict:
    """The gate binding, from the production argv builder (see bootstrap's
    ``_gate_binding``: a receipt that cannot name the exact command it measured
    is not evidence about any gate)."""
    from daedalus.spine.attempt import pytest_gate_argv
    return {
        "argv": [str(v) for v in pytest_gate_argv(gate_paths)],
        "gate_paths": list(gate_paths),
        "gate_scope": "whole-suite" if not gate_paths else "scoped",
        "head": head,
    }


def _write_receipt(root: Path, **overrides) -> None:
    doc = {
        # A receipt that PASSES every check, so a test that flips ONE field is
        # measuring that field and nothing else. `state`, `kill_rate_floor` and
        # `critical_defect_classes` are as load-bearing as the counts: without
        # them the receipt is "not a completed measurement" and every positive
        # control would fail for a reason it was not written to test.
        "state": "measured",
        "kill_rate_floor": B.KILL_RATE_FLOOR,
        "critical_defect_classes": list(B.CRITICAL_DEFECT_CLASSES),
        "head": REAL_SHA,
        "frozen_gate": _frozen_gate(REAL_SHA),
        "measured_at": "2026-07-29T00:00:00+00:00",
        "planted": 12,
        "killed": 10,                 # 83%, above the 80% floor
        "surviving_classes": [],
    }
    doc.update(overrides)
    if "frozen_gate" not in overrides:
        doc["frozen_gate"] = dict(doc["frozen_gate"], head=doc["head"])
    path = root / B.DISCRIMINATION_REL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


class UnreadableRevisionMustRefuseTests(unittest.TestCase):
    """A tree whose revision cannot be determined is not a tree a receipt can
    be tied to. The old code treated "I don't know what HEAD is" as "no reason
    to object"."""

    def test_control_a_matching_receipt_is_accepted(self):
        # Without this the refusal below would prove nothing: it must be
        # possible for this receipt to succeed at all.
        with TemporaryDirectory() as d:
            root = Path(d)
            _write_receipt(root)
            got = B.gate_discrimination(root, head=REAL_SHA)
            self.assertTrue(got.proven, got.reason)

    def test_no_git_and_no_supplied_head_refuses(self):
        # THE FORGERY: a temp dir has no .git, so `_head_sha` returns None.
        # Old behaviour: proven=True on a receipt from any revision at all.
        with TemporaryDirectory() as d:
            root = Path(d)
            _write_receipt(root, head=OTHER_SHA)
            got = B.gate_discrimination(root)          # no head supplied
            self.assertFalse(got.proven)
            self.assertIn("current revision could not be read", got.reason)

    def test_unreadable_revision_refuses_even_a_perfect_receipt(self):
        # Not merely "a stale receipt is refused" -- the refusal must not
        # depend on the receipt being stale, or it is the old bug wearing a
        # different mask.
        with TemporaryDirectory() as d:
            root = Path(d)
            _write_receipt(root)                       # names REAL_SHA
            self.assertFalse(B.gate_discrimination(root).proven)

    def test_an_explicitly_supplied_head_is_still_honoured(self):
        # tools/bootstrap_receipt.py asks about a DIFFERENT revision on
        # purpose, so the parameter must keep working -- the fix resolves HEAD
        # only when the caller supplied none.
        with TemporaryDirectory() as d:
            root = Path(d)
            _write_receipt(root)
            self.assertFalse(B.gate_discrimination(root, head=OTHER_SHA).proven)
            self.assertTrue(B.gate_discrimination(root, head=REAL_SHA).proven)


class ImpossibleCountsMustRefuseTests(unittest.TestCase):
    def test_control_a_plausible_count_is_accepted(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            _write_receipt(root, planted=12, killed=10)
            self.assertTrue(B.gate_discrimination(root, head=REAL_SHA).proven)

    def test_killed_above_planted_refuses(self):
        # THE FORGERY: 99/12 = 825%, which passes an 80% floor.
        with TemporaryDirectory() as d:
            root = Path(d)
            _write_receipt(root, planted=12, killed=99)
            got = B.gate_discrimination(root, head=REAL_SHA)
            self.assertFalse(got.proven)
            self.assertIn("internally inconsistent", got.reason)

    def test_negative_and_degenerate_counts_refuse(self):
        for planted, killed in ((12, -1), (0, 0), (-5, -5), (0, 7)):
            with self.subTest(planted=planted, killed=killed):
                with TemporaryDirectory() as d:
                    root = Path(d)
                    _write_receipt(root, planted=planted, killed=killed)
                    self.assertFalse(
                        B.gate_discrimination(root, head=REAL_SHA).proven)

    def test_a_critical_class_still_outranks_a_perfect_rate(self):
        # Regression guard on the ordering that was already correct: the class
        # check runs BEFORE the rate check, so a flawless score cannot average
        # away a fatal blind spot.
        with TemporaryDirectory() as d:
            root = Path(d)
            _write_receipt(root, planted=12, killed=12,
                           surviving_classes=[B.CRITICAL_DEFECT_CLASSES[0]])
            got = B.gate_discrimination(root, head=REAL_SHA)
            self.assertFalse(got.proven)
            self.assertIn("critical defect class", got.reason)


if __name__ == "__main__":
    unittest.main()
