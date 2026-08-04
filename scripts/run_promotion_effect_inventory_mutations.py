from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_effect_inventory.py"
TESTS = (
    "tests/kernel/test_promotion_effect_inventory.py",
    "tests/kernel/test_promotion_effect_inventory_review.py",
)

MUTATIONS = (
    (
        "accept-noncentral-wiring",
        "if row.wiring is not Wiring.CENTRAL:\n            blockers.append(f\"registry.not_central:{row.wiring.value}\")",
        "if False:\n            blockers.append(f\"registry.not_central:{row.wiring.value}\")",
    ),
    (
        "omit-missing-registry-row",
        "if row is None:\n        blockers.append(\"registry.missing\")",
        "if row is None:\n        pass",
    ),
    (
        "ignore-guard-mismatch",
        "if tuple(row.guard_contracts) != requirement.guard_contracts:\n            blockers.append(\"registry.guards_mismatch\")",
        "if False:\n            blockers.append(\"registry.guards_mismatch\")",
    ),
    (
        "ignore-source-anchor",
        "if name not in calls\n    )",
        "if False\n    )",
    ),
    (
        "omit-ledger-open-effect",
        "for requirement in REQUIREMENTS\n    )",
        "for requirement in REQUIREMENTS\n        if requirement.entrypoint_id != \"kernel.promotion_execution.open\"\n    )",
    ),
    (
        "force-closed",
        "closed = all(finding.status == \"central\" for finding in findings)",
        "closed = True",
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
        sys.stderr.write("baseline failed before mutation campaign\n")
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    survivors: list[str] = []
    try:
        for name, needle, replacement in MUTATIONS:
            if original.count(needle) != 1:
                sys.stderr.write(
                    f"mutation {name} expected one exact source seam, "
                    f"found {original.count(needle)}\n"
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
    print(f"all {len(MUTATIONS)} promotion inventory mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
