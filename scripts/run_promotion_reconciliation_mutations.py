from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_reconciliation.py"
TESTS = (
    "tests/kernel/test_promotion_effect_capability.py",
    "tests/kernel/test_promotion_effect_replay.py",
    "tests/kernel/test_promotion_replay_projection.py",
    "tests/kernel/test_promotion_reconciliation.py",
    "tests/kernel/test_promotion_reconciliation_adversarial.py",
    "tests/kernel/test_promotion_reconciliation_review.py",
)
MUTATIONS = (
    (
        "grant-automatic-execution",
        "        return False\n",
        "        return True  # mutant grants automatic replay\n",
    ),
    (
        "accept-promotion-without-effect-start",
        "    if effect is None:\n"
        "        raise PromotionReconciliationError(\n"
        "            \"promotion execution exists without a top-level effect start\"\n"
        "        )\n",
        "    if effect is None:\n"
        "        return PromotionReconciliationProjection(FRESH, None, None, None)\n",
    ),
    (
        "accept-reversed-start-order",
        "    if effect_started > promotion_started:\n",
        "    if False:  # mutant accepts promotion start before effect start\n",
    ),
    (
        "accept-effect-terminal-while-promotion-pending",
        "    if promotion.completion is None:\n"
        "        if effect.terminal is not None:\n",
        "    if promotion.completion is None:\n"
        "        if False:  # mutant accepts premature effect terminal\n",
    ),
    (
        "accept-terminal-substitution",
        "    _verify_terminal(effect.terminal, expected)\n",
        "    pass  # mutant trusts top-level terminal bytes\n",
    ),
    (
        "accept-reversed-terminal-order",
        "    if effect_finished < promotion_finished:\n",
        "    if False:  # mutant accepts top-level terminal before promotion\n",
    ),
    (
        "mis-map-successful-promotion",
        '            outcome="COMPLETED",\n',
        '            outcome="FAILED",  # mutant loses successful outcome\n',
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
        sys.stderr.write("baseline failed before promotion-reconciliation mutations\n")
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
    print(f"all {len(MUTATIONS)} promotion-reconciliation mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
