from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = (
    ROOT
    / "daedalus"
    / "spine"
    / "promotion_recovery_consumption_inventory.py"
)
TESTS = (
    "tests/test_promotion_recovery_consumption_inventory.py",
    "tests/test_promotion_recovery_consumption_inventory_review.py",
)
MUTATIONS = (
    (
        "falsely-claim-canonical-integration",
        '        "canonical_registry_integrated": False,\n',
        '        "canonical_registry_integrated": True,  # mutant\n',
    ),
    (
        "hide-unguarded-constructor",
        '        wiring="unguarded",\n',
        '        wiring="local_guards",  # mutant\n',
    ),
    (
        "fabricate-constructor-owner-guard",
        "        guard_contracts=(),\n",
        '        guard_contracts=("promotion.owner_recovery_decision",),  # mutant\n',
    ),
    (
        "trust-consumption-as-central",
        '        wiring="local_guards",\n',
        '        wiring="central",  # mutant\n',
    ),
    (
        "classify-read-only-verifier-as-write-entrypoint",
        'SCANNER_METHODS = ("__init__", "consume")\n',
        'SCANNER_METHODS = ("__init__", "consume", "verify_consumption")  # mutant\n',
    ),
    (
        "remove-scanner-integration-blocker",
        '    "static-effect-scanner-does-not-yet-discover-recovery-consumption-writes",\n',
        "",
    ),
    (
        "wildcard-scanner-module",
        "        module == SCANNER_MODULE\n",
        "        module.startswith(SCANNER_MODULE)  # mutant\n",
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
        sys.stderr.write("baseline failed before inventory-delta mutations\n")
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
    print(f"all {len(MUTATIONS)} inventory-delta mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
