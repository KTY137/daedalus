# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "spine" / "effect_boundary.py"
TESTS = (
    "tests/kernel/test_isolated_attempt_effect_inventory_registration.py",
    "tests/kernel/test_isolated_attempt_effect_inventory.py",
)


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one mutation site, found {count}")
    return source.replace(old, new, 1)


def main() -> int:
    original = TARGET.read_bytes()
    source = original.decode("utf-8")
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("attempt effect-inventory mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    class_mapping = '''    if (
        model.module == "daedalus.kernel.attempt_ledger"
        and class_name == "AttemptLedger"
    ):
        return Surface.PYTHON
'''
    lifecycle_row = '''    EntrypointSpec(
        id="kernel.attempt.begin",
        surface=Surface.PYTHON,
        target="daedalus.kernel.attempt_ledger:AttemptLedger.begin",
'''
    mutations = (
        (
            "hide-attempt-ledger-from-static-discovery",
            class_mapping,
            class_mapping.replace("return Surface.PYTHON", "return None"),
        ),
        (
            "remove-canonical-attempt-begin-owner",
            lifecycle_row,
            lifecycle_row.replace(
                'target="daedalus.kernel.attempt_ledger:AttemptLedger.begin",',
                'target="daedalus.kernel.attempt_ledger:AttemptLedger.missing",',
            ),
        ),
    )

    killed: list[str] = []
    try:
        for label, old, new in mutations:
            TARGET.write_text(
                _replace_once(source, old, new, label),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                sys.stderr.write(f"survived mutation: {label}\n")
                return 1
            killed.append(label)
            TARGET.write_bytes(original)
    finally:
        TARGET.write_bytes(original)

    if TARGET.read_bytes() != original:
        raise RuntimeError("mutation runner failed to restore effect_boundary.py")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
