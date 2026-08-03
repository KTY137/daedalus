#!/usr/bin/env python3
"""Kill an overclaim mutation in the ROOT metadata assurance boundary."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TARGET = Path("daedalus/twin/extractors/root_file_adapter.py")
ORIGINAL = '    status = "partial"\n'
REPLACEMENT = '    status = "complete"\n'
TESTS = ("tests/twin/test_root_metadata_assurance_boundary.py",)


def run(root: Path) -> subprocess.CompletedProcess[str]:
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


def tail(result: subprocess.CompletedProcess[str], lines: int = 40) -> str:
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return "\n".join(combined.splitlines()[-lines:])


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    target = root / TARGET
    baseline = run(root)
    if baseline.returncode != 0:
        print("baseline failed; mutation evidence is invalid", file=sys.stderr)
        print(tail(baseline), file=sys.stderr)
        return 2

    source = target.read_text(encoding="utf-8")
    count = source.count(ORIGINAL)
    if count != 1:
        print(f"expected one metadata assurance mutation seam, found {count}", file=sys.stderr)
        return 3
    mutated = source.replace(ORIGINAL, REPLACEMENT, 1)
    try:
        compile(mutated, str(target), "exec")
    except SyntaxError as exc:
        print(f"invalid mutation: {exc}", file=sys.stderr)
        return 4

    try:
        target.write_text(mutated, encoding="utf-8")
        result = run(root)
    finally:
        target.write_text(source, encoding="utf-8")

    if target.read_text(encoding="utf-8") != source:
        print("ROOT metadata adapter was not restored", file=sys.stderr)
        return 5
    if result.returncode == 0:
        print("SURVIVED root-metadata-claims-complete", file=sys.stderr)
        return 1
    print("KILLED root-metadata-claims-complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
