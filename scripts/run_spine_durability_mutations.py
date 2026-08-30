# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "spine" / "durability.py"
TESTS = (
    "tests/test_spine_gate0_durability.py",
    "tests/test_spine_gate0_durability_review.py",
    "tests/test_spine_ledger.py",
    "tests/kernel/test_isolated_attempt_spine_wire_review.py",
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
        sys.stderr.write("Event Store durability mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "downgrade-full-to-normal",
            '            connection.execute("PRAGMA synchronous=FULL")\n',
            '            connection.execute("PRAGMA synchronous=NORMAL")\n',
        ),
        (
            "accept-read-only-writer",
            "    if ledger.read_only:\n",
            "    if False:\n",
        ),
        (
            "silently-rewrite-non-wal-store",
            """            if before.journal_mode != _REQUIRED_JOURNAL_MODE:
                raise Gate0DurabilityError(
                    "Gate-0 Event Store requires existing WAL journal mode"
                )
""",
            """            if before.journal_mode != _REQUIRED_JOURNAL_MODE:
                connection.execute("PRAGMA journal_mode=WAL")
""",
        ),
        (
            "remove-minimum-busy-timeout",
            """            connection.execute(
                f"PRAGMA busy_timeout={max(DEFAULT_BUSY_TIMEOUT_MS, ledger.busy_timeout_ms)}"
            )
""",
            """            connection.execute("PRAGMA busy_timeout=1")
""",
        ),
        (
            "disable-foreign-keys",
            '            connection.execute("PRAGMA foreign_keys=ON")\n',
            '            connection.execute("PRAGMA foreign_keys=OFF")\n',
        ),
        (
            "claim-satisfied-with-normal-sync",
            "        and sync_value == _REQUIRED_SYNCHRONOUS\n",
            "        and sync_value >= 1\n",
        ),
        (
            "skip-post-apply-readback-refusal",
            "    if not status.satisfied:\n",
            "    if False:\n",
        ),
        (
            "weaken-required-sync-constant",
            "_REQUIRED_SYNCHRONOUS = 2  # SQLite FULL\n",
            "_REQUIRED_SYNCHRONOUS = 1  # mutated NORMAL\n",
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
        raise RuntimeError("mutation runner failed to restore durability source")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
