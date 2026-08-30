#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Run bounded mutations over the provider-observation persistence inventory."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/provider_observation_persistence_inventory.py"
BEHAVIOR = "tests/gates/test_provider_observation_persistence_inventory.py"
REVIEW = "tests/gates/test_provider_observation_persistence_inventory_review.py"
CLI = "tests/gates/test_provider_observation_persistence_inventory_cli.py"

MUTATIONS = {
    "false-closure": (
        "    def closed(self) -> bool:\n        return False\n",
        "    def closed(self) -> bool:\n        return True\n",
    ),
    "false-canonical-integration": (
        '            "canonical_inventory_integrated": False,\n',
        '            "canonical_inventory_integrated": True,\n',
    ),
    "false-guard-completeness": (
        '            "guard_contracts_complete": False,\n',
        '            "guard_contracts_complete": True,\n',
    ),
    "drop-rollback-anchor": (
        '("retained rollback", "ROLLBACK", "rollback-idempotent-existing-binding"),\n',
        '("retained rollback", "NOT ROLLBACK", "rollback-idempotent-existing-binding"),\n',
    ),
    "drop-recovery-read-path": (
        'methods["require_bound"], label="require-bound load", predicate=_callee_is("self.load")\n',
        'methods["require_bound"], label="require-bound load", predicate=_callee_is("self.missing")\n',
    ),
    "accept-source-symlink": (
        "        if source_path.is_symlink():\n",
        "        if False and source_path.is_symlink():\n",
    ),
}


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", BEHAVIOR, REVIEW, CLI],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
    )


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    try:
        baseline = _run()
    except subprocess.TimeoutExpired:
        print("baseline timed out", file=sys.stderr)
        return 2
    if baseline.returncode != 0:
        print("baseline failed before mutations", file=sys.stderr)
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    survivors: list[str] = []
    timeouts: list[str] = []
    try:
        for name, (needle, replacement) in MUTATIONS.items():
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            TARGET.write_text(original.replace(needle, replacement, 1), encoding="utf-8")
            try:
                completed = _run()
            except subprocess.TimeoutExpired:
                timeouts.append(name)
            else:
                if completed.returncode == 0:
                    survivors.append(name)
            finally:
                TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    if survivors or timeouts:
        if survivors:
            print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        if timeouts:
            print("timed-out mutations: " + ", ".join(timeouts), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} provider-observation inventory mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
