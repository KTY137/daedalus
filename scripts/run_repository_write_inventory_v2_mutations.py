#!/usr/bin/env python3
"""Run bounded source mutations against the generation-2 inventory tests."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository/write_inventory_v2.py"
TESTS = (
    "tests/gates/test_repository_write_inventory_v2.py",
    "tests/gates/test_repository_write_inventory_v2_review.py",
)
MUTATIONS = {
    "drop-second-base-scan": (
        "base_after = scan_repository_write_surfaces(\n"
        "            repository_root,\n"
        "            source_revision=source_revision,\n"
        "        )",
        "base_after = base_before",
    ),
    "launder-base-digest-binding": (
        "base_before.digest\n"
        "        == delta.base_inventory_digest\n"
        "        == base_after.digest",
        "base_before.digest\n"
        "        == base_before.digest\n"
        "        == base_after.digest",
    ),
    "drop-position-overlap-refusal": (
        "if base_positions.intersection(delta_positions):",
        "if False and base_positions.intersection(delta_positions):",
    ),
    "force-closed": (
        "return not self.blockers",
        "return True",
    ),
    "launder-delta-blocker": (
        "blocking=True,\n"
        "                )\n"
        "                for finding in delta.findings",
        "blocking=False,\n"
        "                )\n"
        "                for finding in delta.findings",
    ),
    "hide-canonical-integration": (
        '"canonical_scanner_integrated": True',
        '"canonical_scanner_integrated": False',
    ),
}


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    failures: list[str] = []
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
            )
            if completed.returncode == 0:
                failures.append(name)
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")
    if failures:
        print("surviving mutations: " + ", ".join(failures), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} repository-write inventory v2 mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
