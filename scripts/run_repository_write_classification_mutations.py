#!/usr/bin/env python3
"""Run bounded source mutations against the classification contract tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository_write_classification.py"
TESTS = (
    "tests/gates/test_repository_write_classification.py",
    "tests/gates/test_repository_write_classification_review.py",
)
MUTATIONS = {
    "force-closed": ('"closed": False', '"closed": True'),
    "forge-evidence-authentication": (
        '"evidence_authenticated": False',
        '"evidence_authenticated": True',
    ),
    "forge-primary-checkout-proof": (
        '"primary_checkout_target_proven": False',
        '"primary_checkout_target_proven": True',
    ),
    "drop-effect-lease-evidence": (
        "EvidenceKind.EFFECT_LEASE_RECEIPT,\n",
        "# mutated: effect lease evidence omitted\n",
    ),
    "accept-stale-inventory-digest": (
        'if value["inventory_digest"] != inventory.digest:',
        'if False and value["inventory_digest"] != inventory.digest:',
    ),
    "accept-duplicate-surface": (
        "if row.surface in by_surface:",
        "if False and row.surface in by_surface:",
    ),
}


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    survivors: list[str] = []
    try:
        for name, (needle, replacement) in MUTATIONS.items():
            if original.count(needle) != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found "
                    f"{original.count(needle)}"
                )
            TARGET.write_text(original.replace(needle, replacement), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *TESTS],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            )
            if completed.returncode == 0:
                survivors.append(name)
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")
    if survivors:
        print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} repository-write classification mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
