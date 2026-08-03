#!/usr/bin/env python3
"""Run a bounded mutation against the evidence-index canonical wire boundary."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SOURCE = Path("daedalus/gates/evidence_io.py")
ORIGINAL = "    if wire != index.to_dict():\n"
MUTATED = "    if False:\n"
TESTS = (
    "tests/gates/test_exact_head_evidence_io.py",
    "tests/gates/test_exact_head_evidence_canonical_wire.py",
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


def _tail(result: subprocess.CompletedProcess[str], lines: int = 50) -> str:
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

    source = target.read_text(encoding="utf-8")
    if source.count(ORIGINAL) != 1:
        print("expected exactly one evidence-index canonical seam", file=sys.stderr)
        return 3
    mutant = source.replace(ORIGINAL, MUTATED, 1)
    try:
        compile(mutant, str(target), "exec")
    except SyntaxError as exc:
        print(f"invalid mutant: {exc}", file=sys.stderr)
        return 4

    try:
        target.write_text(mutant, encoding="utf-8")
        result = _run(root)
    finally:
        target.write_text(source, encoding="utf-8")

    if target.read_text(encoding="utf-8") != source:
        print("evidence index source was not restored", file=sys.stderr)
        return 5
    if result.returncode == 0:
        print("SURVIVED accept-normalized-evidence-index-wire", file=sys.stderr)
        return 1
    print("KILLED accept-normalized-evidence-index-wire")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
