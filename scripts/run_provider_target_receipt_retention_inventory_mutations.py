"""Run a bounded mutation campaign against the retention inventory boundary."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/provider_target_receipt_retention_inventory.py"
TESTS = [
    "tests/gates/test_provider_target_receipt_retention_inventory.py",
    "tests/gates/test_provider_target_receipt_retention_inventory_review.py",
]
MUTANTS = {
    "close_inventory": ('"closed": False,', '"closed": True,'),
    "central_wiring": ('"wiring": "inventory_only",', '"wiring": "central",'),
    "fake_guard": ('"guard_contract_bound": False,', '"guard_contract_bound": True,'),
    "fake_lease": ('"effect_lease_consumed": False,', '"effect_lease_consumed": True,'),
    "permit_duplicate_anchor": ("if len(matches) != 1:", "if not matches:"),
    "drop_last_surface": ("return tuple(sorted(rows))", "return tuple(sorted(rows[:-1]))"),
}


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    failures: list[str] = []
    try:
        for name, (old, new) in MUTANTS.items():
            if original.count(old) != 1:
                raise RuntimeError(f"mutation seam {name} is not unique")
            TARGET.write_text(original.replace(old, new, 1), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *TESTS],
                cwd=ROOT,
                env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
                check=False,
            )
            if completed.returncode == 0:
                failures.append(name)
    finally:
        TARGET.write_text(original, encoding="utf-8")
    if failures:
        print("surviving mutants: " + ", ".join(failures), file=sys.stderr)
        return 1
    print(f"killed {len(MUTANTS)} bounded mutants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
