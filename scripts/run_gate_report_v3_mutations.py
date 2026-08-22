#!/usr/bin/env python3
"""Run bounded mutations over the GateReport-v3 repository-write boundary."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/report_v3.py"
TESTS = (
    "tests/gates/test_gate_report_v3.py",
    "tests/gates/test_gate_report_v3_bounds.py",
    "tests/gates/test_gate_report_v3_drift.py",
    "tests/gates/test_gate_report_v3_review.py",
    "tests/gates/test_gate_report_v3_schema.py",
    "tests/gates/test_gate_report_v3_cli.py",
)

MUTATIONS = {
    "force-closure": (
        """    def closed(self) -> bool:\n        return bool(\n            self.security_boundary_claimed\n            and self.owner_approval_enforced\n            and not self.blockers\n        )\n""",
        """    def closed(self) -> bool:\n        return True\n""",
    ),
    "ignore-missing-inventory-digest": (
        "        if self.repository_write_inventory_sha256 is None:\n",
        "        if False and self.repository_write_inventory_sha256 is None:\n",
    ),
    "ignore-missing-scan-input-digest": (
        "        if self.repository_write_scan_input_sha256 is None:\n",
        "        if False and self.repository_write_scan_input_sha256 is None:\n",
    ),
    "accept-unsupported-inventory-generation": (
        "        if self.repository_write_inventory_generation != 2:\n",
        "        if False and self.repository_write_inventory_generation != 2:\n",
    ),
    "drop-repository-write-failures": (
        """        rows.extend(\n            f\"repository_write_failures:{row}\"\n            for row in self.repository_write_failures\n        )\n""",
        """        rows.extend(())\n""",
    ),
    "launder-scanner-refusal": (
        """            (\"inventory-refused\",),\n            (\"blocker:repository_write_inventory:refused\",),\n""",
        """            (),\n            (),\n""",
    ),
    "omit-inventory-digest-from-wire-body": (
        """        body[\"repository_write_inventory_sha256\"] = (\n            self.repository_write_inventory_sha256\n        )\n""",
        """        body[\"repository_write_inventory_sha256\"] = None\n""",
    ),
    # These two anchors carried an extra indentation level and matched zero
    # times, so the harness aborted on "expected one source anchor, found 0"
    # before it applied any mutation: the whole file was a dead guard.  The
    # fences live at function-body indentation in build_gate0_report_v3.
    "disable-base-report-drift-fence": (
        "    if base_before.to_dict() != base_after.to_dict():\n",
        "    if False and base_before.to_dict() != base_after.to_dict():\n",
    ),
    "disable-repository-inventory-drift-fence": (
        "    if inventory_before != inventory_after:\n",
        "    if False and inventory_before != inventory_after:\n",
    ),
    "disable-v3-monotonicity": (
        "    return tuple(sorted(set(current.blockers) - set(baseline.blockers)))\n",
        "    return ()\n",
    ),
}


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
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
            TARGET.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
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
    print(f"killed {len(MUTATIONS)} GateReport-v3 mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
