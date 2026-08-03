from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TARGET = (
    Path(__file__).resolve().parents[1]
    / "daedalus"
    / "orchestration"
    / "replay_planning.py"
)
TESTS = (
    "tests/orchestration/test_renovation_replay_planning.py",
    "tests/orchestration/test_renovation_replay_planning_review.py",
)

MUTATIONS = (
    (
        "dependency fence",
        'second_observation.state != "not-started" and first_observation.state != "succeeded"',
        'second_observation.state != "not-started" and False',
    ),
    (
        "unknown outcome duplicate execution",
        'action = "reconcile"',
        'action = "execute"',
    ),
    (
        "consumer recomputation",
        "if replay_plan != expected:",
        "if False:",
    ),
)


def _run() -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.setdefault("PYTHONHASHSEED", "0")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=TARGET.parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    original = TARGET.read_bytes()
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("baseline failed before mutation campaign\n")
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    failures: list[str] = []
    try:
        source = original.decode("utf-8")
        for name, old, new in MUTATIONS:
            if source.count(old) != 1:
                failures.append(f"{name}: expected one mutation site")
                continue
            TARGET.write_text(source.replace(old, new, 1), encoding="utf-8")
            result = _run()
            if result.returncode == 0:
                failures.append(f"{name}: mutant survived")
            TARGET.write_bytes(original)
            if TARGET.read_bytes() != original:
                failures.append(f"{name}: source restoration failed")
    finally:
        TARGET.write_bytes(original)

    if failures:
        for failure in failures:
            sys.stderr.write(failure + "\n")
        return 1
    print(f"killed {len(MUTATIONS)} bounded replay-planning mutants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
