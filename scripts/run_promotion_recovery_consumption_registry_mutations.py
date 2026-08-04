from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (
    ROOT / "daedalus" / "spine" / "promotion_recovery_consumption_registry.py"
)
REPORT = (
    ROOT
    / "daedalus"
    / "spine"
    / "promotion_recovery_consumption_registry_report.py"
)
TESTS = (
    "tests/test_promotion_recovery_consumption_registry.py",
    "tests/test_promotion_recovery_consumption_registry_review.py",
)
MUTATIONS = (
    (
        "trust-both-rows-as-central",
        INSTALLER,
        "            wiring = boundary.Wiring(proposed.wiring)\n",
        "            wiring = boundary.Wiring.CENTRAL  # mutant\n",
    ),
    (
        "erase-consumption-owner-guard",
        INSTALLER,
        "                guard_contracts=proposed.guard_contracts,\n",
        "                guard_contracts=(),  # mutant\n",
    ),
    (
        "wildcard-scanner-module",
        INSTALLER,
        "                model.module,\n",
        "                SCANNER_MODULE,  # mutant\n",
    ),
    (
        "omit-guard-map-integration",
        INSTALLER,
        "        existing_guards.update(required_guards)\n",
        "        pass  # mutant: omit guard integration\n",
    ),
    (
        "leave-captured-registry-defaults-stale",
        INSTALLER,
        "    _refresh_captured_registry_defaults(boundary)\n",
        "    pass  # mutant: leave captured defaults stale\n",
    ),
    (
        "falsely-close-scoped-report",
        REPORT,
        '        "closed": False,\n',
        '        "closed": True,  # mutant\n',
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
        REPORT: REPORT.read_text(encoding="utf-8"),
    }
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("baseline failed before recovery-registry mutations\n")
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    survivors: list[str] = []
    try:
        for name, target, needle, replacement in MUTATIONS:
            original = originals[target]
            count = original.count(needle)
            if count != 1:
                sys.stderr.write(
                    f"mutation {name} expected one source seam, found {count}\n"
                )
                return 3
            target.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
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
    print(f"all {len(MUTATIONS)} recovery-registry mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
