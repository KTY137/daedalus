from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kairos" / "promotion_effect_lifecycle.py"
TESTS = (
    "tests/kernel/test_promotion_effect_capability.py",
    "tests/kernel/test_promotion_effect_replay.py",
    "tests/kernel/test_promotion_replay_projection.py",
    "tests/kernel/test_promotion_reconciliation.py",
    "tests/kernel/test_promotion_terminalization.py",
    "tests/kernel/test_promotion_effect_lifecycle.py",
    "tests/kernel/test_promotion_effect_lifecycle_adversarial.py",
    "tests/kernel/test_promotion_effect_lifecycle_review.py",
)
MUTATIONS = (
    (
        "claim-automatic-execution",
        '        "automatic_execution_allowed": False,\n',
        '        "automatic_execution_allowed": True,  # mutant\n',
    ),
    (
        "accept-capability-subject-substitution",
        "    if observed.to_dict() != capability.promotion.to_dict():\n",
        "    if False:  # mutant accepts another promotion subject\n",
    ),
    (
        "skip-fresh-subject-preauthorization",
        "    _preauthorize_exact_subject(\n",
        "    if False:\n        _preauthorize_exact_subject(\n",
    ),
    (
        "skip-effect-lease-grant",
        "    promotion_effect_capability.grant()\n",
        "    pass  # mutant skips lease grant\n",
    ),
    (
        "skip-effect-start-persistence",
        "    effect_begin = promotion_effect_capability.begin()\n",
        "    effect_begin = type('MutantBegin', (), {'execute': True})()\n",
    ),
    (
        "ignore-concurrent-effect-start",
        "    if not effect_begin.execute:\n",
        "    if False:  # mutant re-enters after concurrent effect start\n",
    ),
    (
        "discard-retained-terminal-report",
        "    return promotion.completion.report_dict()\n",
        "    return {}  # mutant discards retained authority\n",
    ),
    (
        "skip-post-delegate-terminalization",
        "    if (\n        after.disposition\n",
        "    if False and (\n        after.disposition\n",
    ),
    (
        "misclassify-complete-replay",
        "    if disposition is PromotionReconciliationDisposition.COMPLETE:\n",
        "    if False:  # mutant does not replay complete state\n",
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
        sys.stderr.write("baseline failed before promotion-effect-lifecycle mutations\n")
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
    print(f"all {len(MUTATIONS)} promotion-effect-lifecycle mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
