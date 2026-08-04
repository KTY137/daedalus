from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_effect_replay.py"
TESTS = (
    "tests/kernel/test_promotion_effect_capability.py",
    "tests/kernel/test_promotion_effect_replay.py",
    "tests/kernel/test_promotion_effect_replay_adversarial.py",
    "tests/kernel/test_promotion_effect_replay_review.py",
)
MUTATIONS = (
    (
        "open-writable-database",
        'resolved.as_uri() + "?mode=ro",\n',
        'resolved.as_uri() + "?mode=rw",  # mutant opens writable\n',
    ),
    (
        "skip-query-only-readback",
        '        if int(conn.execute("PRAGMA query_only").fetchone()[0]) != 1:\n',
        '        if False:  # mutant trusts query_only without readback\n',
    ),
    (
        "accept-request-byte-substitution",
        '        "request_json": canonical_json(execution.to_dict()),\n',
        '        "request_json": row["request_json"],  # mutant trusts retained bytes\n',
    ),
    (
        "accept-terminal-state-substitution",
        '        "state": receipt.outcome,\n',
        '        "state": row["state"],  # mutant trusts retained state\n',
    ),
    (
        "accept-ambiguous-execution-identity",
        "        if len(execution_rows) > 1:\n",
        "        if False:  # mutant accepts ambiguous execution identity\n",
    ),
    (
        "accept-orphan-execution",
        "            if execution_rows:\n",
        "            if False:  # mutant hides an orphan execution\n",
    ),
)


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("baseline failed before promotion-effect-replay mutations\n")
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    survivors: list[str] = []
    try:
        for name, needle, replacement in MUTATIONS:
            count = original.count(needle)
            if count != 1:
                sys.stderr.write(
                    f"mutation {name} expected one source seam, found {count}\n"
                )
                return 3
            TARGET.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                survivors.append(name)
                sys.stderr.write(f"SURVIVED: {name}\n")
            else:
                print(f"killed: {name}")
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    if survivors:
        sys.stderr.write("surviving mutations: " + ", ".join(survivors) + "\n")
        return 1
    print(f"all {len(MUTATIONS)} promotion-effect-replay mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
