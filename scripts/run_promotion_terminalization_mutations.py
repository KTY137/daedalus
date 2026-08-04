#!/usr/bin/env python3
"""Run bounded source mutations for promotion effect terminalization."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


TARGET = Path("daedalus/kernel/promotion_terminalization.py")
TESTS = (
    "tests/kernel/test_promotion_terminalization.py",
    "tests/kernel/test_promotion_terminalization_review.py",
)

MUTATIONS = {
    "admit-promotion-pending": (
        "is not PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED",
        "not in {PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED, PromotionReconciliationDisposition.PROMOTION_PENDING}",
    ),
    "forge-completed-outcome": (
        "outcome=expected.outcome,",
        'outcome="COMPLETED",',
    ),
    "drop-output-binding": (
        "output_digests=expected.output_digests,",
        "output_digests=(),",
    ),
    "drop-detail-binding": (
        "detail_sha256=expected.detail_sha256,",
        "detail_sha256=None,",
    ),
    "accept-regressed-clock": (
        "if finished_at < promotion_finished_at:",
        "if False and finished_at < promotion_finished_at:",
    ),
    "accept-written-retained-substitution": (
        "if retained.receipt_sha256 != written.receipt_sha256:",
        "if False and retained.receipt_sha256 != written.receipt_sha256:",
    ),
    "skip-post-write-reconciliation": (
        """    try:
        retained = _complete_terminal(capability, promotion_ledger)
    except PromotionReconciliationError as exc:
""",
        """    try:
        retained = written
    except PromotionReconciliationError as exc:
""",
    ),
}


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    baseline = _run()
    if baseline.returncode != 0:
        print("baseline failed; refusing mutation claims")
        print(baseline.stdout)
        return 2

    survivors: list[str] = []
    try:
        for name, (needle, replacement) in MUTATIONS.items():
            if original.count(needle) != 1:
                print(f"mutation seam {name!r} is not unique")
                return 3
            TARGET.write_text(original.replace(needle, replacement), encoding="utf-8")
            result = _run()
            if result.returncode == 0:
                survivors.append(name)
                print(f"SURVIVED: {name}")
            else:
                print(f"KILLED: {name}")
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    if survivors:
        print("surviving mutations: " + ", ".join(survivors))
        return 1
    print(f"all {len(MUTATIONS)} terminalization mutations killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
