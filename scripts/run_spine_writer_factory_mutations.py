from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "spine" / "durability.py"
TESTS = (
    "tests/test_spine_gate0_writer_factory.py",
    "tests/test_spine_gate0_writer_factory_review.py",
    "tests/test_spine_gate0_durability.py",
    "tests/test_spine_gate0_durability_review.py",
    "tests/kernel/test_attempt_durability_admission.py",
    "tests/kernel/test_attempt_durability_admission_review.py",
    "tests/kernel/test_isolated_attempt_lifecycle.py",
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
        sys.stderr.write("Gate-0 writer-factory mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "opening-profile-downgrade-to-normal",
            '        self._conn.execute("PRAGMA synchronous=FULL")\n',
            '        self._conn.execute("PRAGMA synchronous=NORMAL")\n',
        ),
        (
            "factory-bypasses-opening-profile",
            """        ledger = _Gate0OpeningSpineLedger(
            path,
""",
            """        ledger = SpineLedger(
            path,
""",
        ),
        (
            "factory-skips-final-readback-refusal",
            """        status = inspect_gate0_durability(ledger)
        if not status.satisfied:
            raise Gate0DurabilityError(
                "new Gate-0 Event-Store writer failed opening readback"
            )
""",
            """        status = inspect_gate0_durability(ledger)
        if False:
            raise Gate0DurabilityError(
                "new Gate-0 Event-Store writer failed opening readback"
            )
""",
        ),
        (
            "factory-removes-minimum-timeout",
            "        timeout = max(DEFAULT_BUSY_TIMEOUT_MS, int(busy_timeout_ms))\n",
            "        timeout = int(busy_timeout_ms)\n",
        ),
        (
            "factory-leaks-writer-on-weak-readback",
            """    except Gate0DurabilityError:
        if "ledger" in locals():
            ledger.close()
        raise
""",
            """    except Gate0DurabilityError:
        raise
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
        raise RuntimeError("mutation runner failed to restore durability source")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
