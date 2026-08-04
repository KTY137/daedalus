from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_effect_reconcile.py"
TESTS = (
    "tests/kernel/test_promotion_effect_reconcile.py",
    "tests/kernel/test_promotion_effect_reconcile_review.py",
)
MUTATIONS = (
    (
        "accept-nonreconcilable-state",
        '    if decision.action != "reconcile_effect_terminal":\n'
        "        raise PromotionEffectReconciliationRefused(\n"
        "            f\"promotion effect reconciliation refused state {decision.action!r}\"\n"
        "        )\n",
        '    if False:  # mutant accepts fresh or pending state\n'
        "        raise PromotionEffectReconciliationRefused(\n"
        "            f\"promotion effect reconciliation refused state {decision.action!r}\"\n"
        "        )\n",
    ),
    (
        "force-completed-outcome",
        "            outcome=decision.expected_effect_outcome,\n",
        '            outcome="COMPLETED",  # mutant hides faulted promotion\n',
    ),
    (
        "detach-report-output",
        "            output_digests=decision.expected_output_digests,\n",
        "            output_digests=(),  # mutant drops report binding\n",
    ),
    (
        "detach-promotion-receipt-detail",
        "            detail_sha256=decision.expected_detail_sha256,\n",
        "            detail_sha256=None,  # mutant drops receipt binding\n",
    ),
    (
        "use-wall-clock-terminal-time",
        "    finished_at = _completion_time(promotion.completion.receipt.completed_at)\n",
        "    finished_at = datetime.now(timezone.utc)  # mutant loses determinism\n",
    ),
    (
        "skip-post-write-exact-replay-check",
        "    replayed = _inspect_after_terminal_attempt(\n"
        "        capability,\n"
        "        promotion_ledger,\n"
        "        context=\"reconciled terminal did not become an exact report replay\",\n"
        "    )\n",
        "    replayed = decision  # mutant trusts pre-write state\n",
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
        sys.stderr.write("baseline failed before promotion reconciliation mutations\n")
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
    print(f"all {len(MUTATIONS)} promotion reconciliation mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
