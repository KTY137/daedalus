from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = (
    ROOT
    / "daedalus"
    / "spine"
    / "promotion_recovery_consumption_store_inventory.py"
)
TESTS = (
    "tests/test_promotion_recovery_consumption_store_inventory.py",
    "tests/test_promotion_recovery_consumption_store_inventory_review.py",
)
MUTATIONS = (
    (
        "falsely-claim-registry-integration",
        '        "canonical_registry_integrated": False,\n',
        '        "canonical_registry_integrated": True,  # mutant\n',
    ),
    (
        "falsely-claim-scanner-integration",
        '        "canonical_scanner_integrated": False,\n',
        '        "canonical_scanner_integrated": True,  # mutant\n',
    ),
    (
        "hide-unguarded-initializer",
        '        wiring="unguarded",\n',
        '        wiring="local_guards",  # mutant\n',
    ),
    (
        "fabricate-initializer-guard",
        "        guard_contracts=(),\n",
        '        guard_contracts=("promotion.owner_recovery_decision",),  # mutant\n',
    ),
    (
        "drop-filesystem-write-effect",
        '        effects=("filesystem_write",),\n',
        "        effects=(),  # mutant\n",
    ),
    (
        "wildcard-scanner-module",
        "    return module == SCANNER_MODULE and function == SCANNER_FUNCTION\n",
        (
            "    return module.startswith(SCANNER_MODULE) and "
            "function == SCANNER_FUNCTION  # mutant\n"
        ),
    ),
    (
        "accept-stale-source-revision",
        "    if source_revision != BASE_REVISION:\n",
        "    if False:  # mutant\n",
    ),
    (
        "remove-effect-lease-blocker",
        '    "initializer-not-bound-to-persisted-effect-lease",\n',
        "",
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
        sys.stderr.write("baseline failed before store-inventory mutations\n")
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
    print(f"all {len(MUTATIONS)} store-inventory mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
