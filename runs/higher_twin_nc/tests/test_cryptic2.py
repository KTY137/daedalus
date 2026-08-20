"""Slice 4 (watchdog mission): H-CRYPT expansion.

Pre-registered expectations (TDD, written before the implementation):

- `walk_edits(L, variant)` produces a DETERMINISTIC, numbered sequence of L
  neutral edits: comment, whitespace and reorder variants targeting BOTH
  calib.py and checks.py. Same inputs -> same sequence; different variants
  -> different sequences; each one-shot reorder edit appears at most once
  per walk (a silently repeated reorder would be a no-op and inflate L).
- `run_expansion` runs walks for L in a configurable ladder with several
  numbered variants per L against a probe set, certifies neutrality via
  the full evaluator outcome, probes on baseline and endpoint, and writes
  per-fixture flip rates plus an anchored receipt chain.
- Measurement expectation (pre-registered): with this edit family the flip
  rate stays 0 across all L on every fixture — deterministic column/doc
  probes do not read code layout. A nonzero rate would be the H-CRYPT
  signal; zero is honest negative evidence, archived (no null-death call:
  the family is still layout-only).
- Any flip at L=0 invalidates the run (harness nondeterminism).
"""
from pathlib import Path

import assay
import cryptic
import operators

ROOT = Path(__file__).resolve().parents[1]


def test_walk_edits_deterministic_numbered_and_file_covering():
    a = cryptic.walk_edits(16, 0)
    b = cryptic.walk_edits(16, 0)
    assert [e.name for e in a] == [e.name for e in b]
    assert len(a) == 16
    assert len({e.name for e in a}) == 16, "edits must be pairwise distinct"
    other = cryptic.walk_edits(16, 1)
    assert [e.name for e in other] != [e.name for e in a]
    names = " ".join(e.name for e in a)
    assert "calib" in names and "checks" in names
    for L in (2, 4, 8, 16):
        seq = cryptic.walk_edits(L, 2)
        assert len(seq) == L
        reorders = [e.name for e in seq if e.name.startswith("reorder")]
        assert len(reorders) == len(set(reorders)), "reorders are one-shot"


def test_walk_edits_apply_cleanly(tmp_path):
    import shutil
    tree = tmp_path / "tree"
    shutil.copytree(ROOT / "fixtures" / "pumplab", tree,
                    ignore=shutil.ignore_patterns("__pycache__"))
    for edit in cryptic.walk_edits(16, 1):
        edit.apply(tree)  # _must_replace raises if a target is missing


def test_expansion_small_run(tmp_path):
    result = cryptic.run_expansion(
        {"sensorlab": (ROOT / "fixtures" / "sensorlab",
                       operators.standard_ops)},
        tmp_path / "out", ladder=(0, 2), variants=2)
    fx = result["fixtures"]["sensorlab"]
    assert fx["l0_ok"] is True
    assert fx["acceptance_rate"] == 1.0
    for walk in fx["walks"]:
        assert walk["neutral_certified"] is True
        assert walk["flip_rate"] == 0.0
    # L=0 runs once; L=2 runs `variants` times with distinct edit sequences
    l2 = [w for w in fx["walks"] if w["L"] == 2]
    assert len(l2) == 2 and l2[0]["edits"] != l2[1]["edits"]
    assert assay.verify_chain(
        tmp_path / "out" / "receipts.jsonl",
        expected_head=result["receipt_head"],
        expected_count=result["receipt_count"]) is True
