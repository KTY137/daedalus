from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_effect_replay.py"
TESTS = (
    "tests/kernel/test_promotion_effect_replay_decision.py",
    "tests/kernel/test_promotion_effect_replay_decision_review.py",
)
MUTATIONS = (
    (
        "accept-promotion-without-effect-start",
        "        if promotion is not None:\n"
        "            raise PromotionEffectReplayMismatch(\n"
        "                \"promotion execution exists without top-level Effect-Lease start\"\n"
        "            )\n",
        "        if False:  # mutant accepts promotion without top-level start\n"
        "            raise PromotionEffectReplayMismatch(\n"
        "                \"promotion execution exists without top-level Effect-Lease start\"\n"
        "            )\n",
    ),
    (
        "skip-cross-ledger-start-order",
        "    if promotion is not None:\n"
        "        _enforce_start_order(effect, promotion)\n",
        "    if False:  # mutant skips cross-ledger start chronology\n"
        "        _enforce_start_order(effect, promotion)\n",
    ),
    (
        "regrant-fresh-on-pending-effect",
        "                action=\"pending_reconciliation\",\n"
        "                effect=effect,\n"
        "                promotion=promotion,\n",
        "                action=\"fresh\",  # mutant permits duplicate execution\n"
        "                effect=effect,\n"
        "                promotion=promotion,\n",
    ),
    (
        "accept-report-output-substitution",
        "    if terminal.output_digests != outputs:\n"
        "        mismatches.append(\"output_digests\")\n",
        "    if False:  # mutant accepts substituted report output\n"
        "        mismatches.append(\"output_digests\")\n",
    ),
    (
        "accept-report-detail-substitution",
        "    if terminal.detail_sha256 != detail:\n"
        "        mismatches.append(\"detail_sha256\")\n",
        "    if False:  # mutant accepts substituted promotion receipt detail\n"
        "        mismatches.append(\"detail_sha256\")\n",
    ),
    (
        "accept-failed-effect-with-terminal-promotion",
        "    if effect.state != \"COMPLETED\":\n"
        "        raise PromotionEffectReplayMismatch(\n"
        "            \"failed or cancelled Effect Lease contradicts terminal promotion report\"\n"
        "        )\n",
        "    if False:  # mutant accepts failed effect with retained promotion report\n"
        "        raise PromotionEffectReplayMismatch(\n"
        "            \"failed or cancelled Effect Lease contradicts terminal promotion report\"\n"
        "        )\n",
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
        sys.stderr.write("baseline failed before promotion-effect replay mutations\n")
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
            TARGET.write_text(original.replace(needle, replacement, 1), encoding="utf-8")
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
    print(f"all {len(MUTATIONS)} promotion-effect replay mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
