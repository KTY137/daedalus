from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_recovery.py"
TESTS = (
    "tests/kernel/test_promotion_recovery_plan.py",
    "tests/kernel/test_promotion_recovery_plan_review.py",
)
MUTATIONS = (
    (
        "allow-automatic-reexecution",
        '        "automatic_external_reexecution": False,\n',
        '        "automatic_external_reexecution": True,  # mutant\n',
    ),
    (
        "skip-owner-decision-for-effect-only",
        "        \"owner_decision_required\": projection.disposition\n        in {\n",
        "        \"owner_decision_required\": False and projection.disposition\n        in {\n",
    ),
    (
        "map-effect-only-to-no-action",
        "        PromotionRecoveryAction.OWNER_DECISION_BEFORE_EFFECT_CANCELLATION\n",
        "        PromotionRecoveryAction.NONE  # mutant\n",
    ),
    (
        "discard-effect-start-binding",
        "            None if effect is None else effect.start.receipt_sha256\n",
        "            None  # mutant\n",
    ),
    (
        "discard-plan-digest-binding",
        "        plan_sha256=canonical_sha(body),\n",
        "        plan_sha256=\"0\" * 64,  # mutant\n",
    ),
)


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("baseline failed before promotion-recovery mutations\n")
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    survivors: list[str] = []
    try:
        for name, needle, replacement in MUTATIONS:
            count = original.count(needle)
            if count != 1:
                sys.stderr.write(
                    f"mutation {name} expected one source seam, found {count}\n"
                )
                return 3
            TARGET.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                survivors.append(name)
                sys.stderr.write(f"SURVIVED: {name}\n")
            else:
                print(f"killed: {name}")
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    if survivors:
        sys.stderr.write("surviving mutations: " + ", ".join(survivors) + "\n")
        return 1
    print(f"all {len(MUTATIONS)} promotion-recovery mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
