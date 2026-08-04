from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "daedalus" / "spine" / "promotion_effect_registry.py"
PACKAGE_INIT = ROOT / "daedalus" / "spine" / "__init__.py"
TESTS = (
    "tests/kernel/test_promotion_effect_rows.py",
    "tests/kernel/test_promotion_effect_rows_review.py",
    "tests/kernel/test_promotion_effect_registry.py",
    "tests/kernel/test_promotion_effect_registry_review.py",
    "tests/kernel/test_promotion_effect_inventory.py",
    "tests/kernel/test_promotion_effect_inventory_review.py",
)
MUTATIONS = (
    (
        "skip-package-install",
        PACKAGE_INIT,
        "_install_promotion_execution_rows(_effect_boundary)",
        "pass  # mutant skips canonical promotion-row installation",
        1,
    ),
    (
        "accept-partial-installation",
        INSTALLER,
        "    if any(row is not None for row in present):\n",
        "    if all(row is not None for row in present):\n",
        1,
    ),
    (
        "accept-reordered-installed-rows",
        INSTALLER,
        "        if tuple(boundary.ENTRYPOINTS[-len(required) :]) != required:\n"
        "            raise RuntimeError(\n"
        "                \"promotion execution rows are not the exact ordered registry suffix\"\n"
        "            )\n",
        "        pass  # mutant accepts reordered exact promotion rows\n",
        1,
    ),
    (
        "change-expected-complete-identity",
        INSTALLER,
        '    "kernel.promotion_execution.complete",\n',
        '    "kernel.promotion_execution.complete.removed",\n',
        2,
    ),
    (
        "remove-open-uniqueness-anchor",
        INSTALLER,
        '        "_install_single_start_invariant",\n',
        '        "_install_single_start_invariant_removed",\n',
        1,
    ),
    (
        "leave-captured-defaults-stale",
        INSTALLER,
        "    if len(boundary.REGISTRY_BY_ID) != len(boundary.ENTRYPOINTS):\n"
        "        raise RuntimeError(\"promotion execution installation created duplicate ids\")\n"
        "    _refresh_captured_registry_defaults(boundary)\n",
        "    if len(boundary.REGISTRY_BY_ID) != len(boundary.ENTRYPOINTS):\n"
        "        raise RuntimeError(\"promotion execution installation created duplicate ids\")\n"
        "    pass  # mutant leaves captured registry defaults stale\n",
        1,
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
    originals = {
        INSTALLER: INSTALLER.read_text(encoding="utf-8"),
        PACKAGE_INIT: PACKAGE_INIT.read_text(encoding="utf-8"),
    }
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("baseline failed before promotion-registry mutations\n")
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    survivors: list[str] = []
    try:
        for name, target, needle, replacement, expected_count in MUTATIONS:
            original = originals[target]
            count = original.count(needle)
            if count != expected_count:
                sys.stderr.write(
                    f"mutation {name} expected {expected_count} source seams, found {count}\n"
                )
                return 3
            target.write_text(original.replace(needle, replacement, 1), encoding="utf-8")
            result = _run()
            if result.returncode == 0:
                survivors.append(name)
                sys.stderr.write(f"SURVIVED: {name}\n")
            else:
                print(f"killed: {name}")
            target.write_text(original, encoding="utf-8")
    finally:
        for target, original in originals.items():
            target.write_text(original, encoding="utf-8")

    if survivors:
        sys.stderr.write("surviving mutations: " + ", ".join(survivors) + "\n")
        return 1
    print(f"all {len(MUTATIONS)} promotion-registry mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
