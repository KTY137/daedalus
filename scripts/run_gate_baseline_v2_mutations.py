# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "daedalus" / "gates" / "baseline.py"
VERIFIER = ROOT / "daedalus" / "gates" / "baseline_verifier.py"
TESTS = (
    "tests/gates/test_gate_baseline_v2.py",
    "tests/gates/test_gate_baseline_cli.py",
    "tests/gates/test_gate_baseline_v2_schema.py",
    "tests/gates/test_gate_baseline_v2_review.py",
    "tests/gates/test_gate_baseline_v2_review_fixed.py",
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
    originals = {
        BASELINE: BASELINE.read_bytes(),
        VERIFIER: VERIFIER.read_bytes(),
    }
    sources = {
        path: raw.decode("utf-8") for path, raw in originals.items()
    }
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("Gate baseline mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            BASELINE,
            "allow-baseline-without-writer-inventory",
            """    if writer_digest is None:
        raise GateBaselineBindingError(
            "Gate baseline requires a bound Event-Store writer inventory"
        )
""",
            """    if False:
        raise GateBaselineBindingError(
            "Gate baseline requires a bound Event-Store writer inventory"
        )
""",
        ),
        (
            BASELINE,
            "accept-unpinned-baseline-digest",
            """    if not _constant_time_equal(expected_digest, baseline.digest):
        raise GateBaselineBindingError("expected baseline digest mismatch")
""",
            """    if False:
        raise GateBaselineBindingError("expected baseline digest mismatch")
""",
        ),
        (
            BASELINE,
            "omit-new-blockers",
            "    new = tuple(sorted(current_blockers - baseline_blockers))\n",
            "    new = ()\n",
        ),
        (
            BASELINE,
            "always-pass-monotonicity",
            '        status="passed" if not new else "failed",\n',
            '        status="passed",\n',
        ),
        (
            BASELINE,
            "trust-serialized-receipt-status",
            """        expected_status = "passed" if not self.new_blockers else "failed"
        if self.status != expected_status:
            raise ValueError("monotonicity status does not match new blockers")
""",
            """        expected_status = self.status
        if self.status != expected_status:
            raise ValueError("monotonicity status does not match new blockers")
""",
        ),
        (
            BASELINE,
            "accept-duplicate-json-keys",
            "            object_pairs_hook=_reject_duplicate_keys,\n",
            "            object_pairs_hook=dict,\n",
        ),
        (
            BASELINE,
            "accept-nonrevision-tree",
            '_REVISION = re.compile(r"^[0-9a-f]{40}$")\n',
            '_REVISION = re.compile(r"^.+$")\n',
        ),
        (
            VERIFIER,
            "skip-receipt-recomputation-comparison",
            """    if receipt != recomputed:
        raise GateBaselineBindingError(
            "monotonicity receipt does not match recomputed evidence"
        )
""",
            """    if False:
        raise GateBaselineBindingError(
            "monotonicity receipt does not match recomputed evidence"
        )
""",
        ),
    )

    killed: list[str] = []
    try:
        for path, label, old, new in mutations:
            path.write_text(
                _replace_once(sources[path], old, new, label),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                sys.stderr.write(f"survived mutation: {label}\n")
                return 1
            killed.append(label)
            path.write_bytes(originals[path])
    finally:
        for path, raw in originals.items():
            path.write_bytes(raw)

    for path, raw in originals.items():
        if path.read_bytes() != raw:
            raise RuntimeError(f"mutation runner failed to restore {path.name}")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
