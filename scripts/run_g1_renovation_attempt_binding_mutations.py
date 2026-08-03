#!/usr/bin/env python3
"""Run bounded mutations against the Renovation attempt-binding boundary."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SOURCE = Path("daedalus/orchestration/attempt_bindings.py")
TESTS = (
    "tests/orchestration/test_renovation_work_items.py",
    "tests/orchestration/test_renovation_attempt_bindings.py",
    "tests/orchestration/test_renovation_attempt_bindings_review.py",
)
MUTATIONS = (
    (
        "accept-forged-replay-key",
        "            if binding.replay_key != expected_replay:\n",
        "            if False:\n",
    ),
    (
        "accept-foreign-runtime-authority",
        "            if attempt.runtime_manifest_sha256 != runtime_digest:\n",
        "            if False:\n",
    ),
    (
        "accept-noncanonical-attempt-plan-wire",
        "    if dict(payload) != value.to_dict():\n",
        "    if False:\n",
    ),
)


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = "0"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _tail(result: subprocess.CompletedProcess[str], lines: int = 60) -> str:
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return "\n".join(combined.splitlines()[-lines:])


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    target = root / SOURCE
    baseline = _run(root)
    if baseline.returncode != 0:
        print("baseline failed; mutation evidence is invalid", file=sys.stderr)
        print(_tail(baseline), file=sys.stderr)
        return 2

    original_source = target.read_text(encoding="utf-8")
    for name, original, mutated in MUTATIONS:
        if original_source.count(original) != 1:
            print(f"expected exactly one mutation seam for {name}", file=sys.stderr)
            return 3
        mutant = original_source.replace(original, mutated, 1)
        try:
            compile(mutant, str(target), "exec")
        except SyntaxError as exc:
            print(f"invalid mutant {name}: {exc}", file=sys.stderr)
            return 4
        try:
            target.write_text(mutant, encoding="utf-8")
            result = _run(root)
        finally:
            target.write_text(original_source, encoding="utf-8")
        if target.read_text(encoding="utf-8") != original_source:
            print("attempt-binding source was not restored", file=sys.stderr)
            return 5
        if result.returncode == 0:
            print(f"SURVIVED {name}", file=sys.stderr)
            return 1
        print(f"KILLED {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
