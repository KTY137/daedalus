from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "attempt_spine_reader.py"
TESTS = (
    "tests/kernel/test_isolated_attempt_time_tampering.py",
    "tests/kernel/test_isolated_attempt_time_and_preflight.py",
    "tests/kernel/test_isolated_attempt_lifecycle.py",
    "tests/kernel/test_isolated_attempt_lifecycle_adversarial.py",
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
        sys.stderr.write("attempt event-time mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "accept-arbitrary-historical-record-time",
            "_MAX_TRANSITION_SKEW_SECONDS = 60.0",
            "_MAX_TRANSITION_SKEW_SECONDS = 10**12",
        ),
        (
            "accept-record-time-after-event",
            "    if delta < 0:\n        raise AttemptStateError(\n            f\"{label} record time follows its Event-Store transition\"\n        )\n",
            "    if False:\n        raise AttemptStateError(\n            f\"{label} record time follows its Event-Store transition\"\n        )\n",
        ),
        (
            "skip-terminal-time-binding",
            """                if state == STATE_COMPLETED:
                    _transition_time(
                        _terminal_time(terminal_result),
                        resolved_ts,
                        label="attempt completion",
                    )
""",
            "",
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
        raise RuntimeError("mutation runner failed to restore attempt_spine_reader.py")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
