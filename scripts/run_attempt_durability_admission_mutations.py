from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "attempt_ledger.py"
TESTS = (
    "tests/kernel/test_attempt_durability_admission.py",
    "tests/test_spine_gate0_durability.py",
    "tests/test_spine_gate0_durability_review.py",
    "tests/kernel/test_isolated_attempt_lifecycle.py",
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
        sys.stderr.write("Attempt durability mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "bypass-durability-admission",
            """            self.durability_status: Gate0DurabilityStatus = (
                enforce_gate0_durability(self.spine)
            )
""",
            """            self.durability_status = None
""",
        ),
        (
            "restore-second-writer-connection",
            "            with self.spine._txn() as connection:\n",
            "            with sqlite3.connect(self.path) as connection:\n",
        ),
        (
            "install-attempt-index-before-durability",
            """        try:
            self.durability_status: Gate0DurabilityStatus = (
                enforce_gate0_durability(self.spine)
            )
""",
            """        self.path = self.spine.path
        self._install_single_start_invariant()
        try:
            self.durability_status: Gate0DurabilityStatus = (
                enforce_gate0_durability(self.spine)
            )
""",
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
        raise RuntimeError("mutation runner failed to restore Attempt source")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
