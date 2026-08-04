from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_terminalization.py"
TESTS = (
    "tests/kernel/test_promotion_effect_capability.py",
    "tests/kernel/test_promotion_effect_replay.py",
    "tests/kernel/test_promotion_replay_projection.py",
    "tests/kernel/test_promotion_reconciliation.py",
    "tests/kernel/test_promotion_reconciliation_outcomes.py",
    "tests/kernel/test_promotion_terminalization.py",
    "tests/kernel/test_promotion_terminalization_outcomes.py",
    "tests/kernel/test_promotion_terminalization_adversarial.py",
    "tests/kernel/test_promotion_terminalization_review.py",
)
MUTATIONS = (
    (
        "accept-pending-promotion-state",
        "        is not PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED\n",
        "        is not PromotionReconciliationDisposition.PROMOTION_PENDING\n",
    ),
    (
        "use-live-expiring-facade-instead-of-reconciliation-authority",
        "        written = capability.authorization.effect_ledger.finish(\n",
        "        written = capability.authorization.finish_effect(\n",
    ),
    (
        "erase-terminal-outputs",
        "            output_digests=expected.output_digests,\n",
        "            output_digests=(),  # mutant erases bound outputs\n",
    ),
    (
        "substitute-terminal-detail",
        "            detail_sha256=expected.detail_sha256,\n",
        '            detail_sha256="0" * 64,  # mutant substitutes detail\n',
    ),
    (
        "trust-any-terminalization-race",
        "        if after_race.disposition is PromotionReconciliationDisposition.COMPLETE:\n",
        "        if True:  # mutant trusts any lost race\n",
    ),
    (
        "skip-post-write-reprojection",
        "    after = inspect_promotion_reconciliation(capability, promotion_ledger)\n",
        "    after = before  # mutant trusts the requested write\n",
    ),
    (
        "accept-writer-return-substitution",
        "    if result.terminal != written:\n",
        "    if False:  # mutant trusts substituted writer return\n",
    ),
    (
        "mislabel-fresh-terminalization-as-replay",
        "    result = _complete_result(after, replayed=False)\n",
        "    result = _complete_result(after, replayed=True)\n",
    ),
    (
        "skip-capability-type-check",
        "    if not isinstance(capability, PromotionEffectCapability):\n",
        "    if False:  # mutant accepts arbitrary capability\n",
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
        sys.stderr.write("baseline failed before promotion-terminalization mutations\n")
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
    print(f"all {len(MUTATIONS)} promotion-terminalization mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
