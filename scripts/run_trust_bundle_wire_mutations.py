#!/usr/bin/env python3
"""Run bounded mutations against the signed trust-bundle wire strangler."""
from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from pathlib import Path


@dataclasses.dataclass(frozen=True)
class Mutation:
    mutation_id: str
    relative_path: str
    original: str
    replacement: str


MUTATIONS = (
    Mutation(
        "accept-normalized-trust-bundle-wire",
        "daedalus/gates/trust_bundle_io.py",
        "    if wire != bundle.to_dict():\n",
        "    if False:\n",
    ),
    Mutation(
        "leave-direct-module-parser-permissive",
        "daedalus/gates/__init__.py",
        "_trust_bundle.parse_evidence_trust_bundle = parse_evidence_trust_bundle\n",
        "# mutation removed compatibility parser strangler\n",
    ),
    Mutation(
        "leave-direct-module-loader-permissive",
        "daedalus/gates/__init__.py",
        "_trust_bundle.load_evidence_trust_bundle = load_evidence_trust_bundle\n",
        "# mutation removed compatibility loader strangler\n",
    ),
)

FOCUSED_TESTS = (
    "tests/gates/test_exact_head_evidence.py",
    "tests/gates/test_exact_head_evidence_io.py",
    "tests/gates/test_exact_head_evidence_canonical_wire.py",
    "tests/gates/test_evidence_trust_bundle.py",
    "tests/gates/test_evidence_trust_bundle_review.py",
    "tests/gates/test_evidence_trust_bundle_canonical_wire.py",
    "tests/gates/test_gate0_release_assessment.py",
)


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = "0"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *FOCUSED_TESTS],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _tail(result: subprocess.CompletedProcess[str], lines: int = 60) -> str:
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return "\n".join(combined.splitlines()[-lines:])


def _mutate(source: str, mutation: Mutation) -> str:
    count = source.count(mutation.original)
    if count != 1:
        raise RuntimeError(
            f"{mutation.mutation_id}: expected one mutation seam, found {count}"
        )
    return source.replace(mutation.original, mutation.replacement, 1)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    baseline = _run(root)
    if baseline.returncode != 0:
        print("baseline focused suite failed; mutation evidence is invalid", file=sys.stderr)
        print(_tail(baseline), file=sys.stderr)
        return 2

    survivors: list[str] = []
    invalid: list[str] = []
    for mutation in MUTATIONS:
        target = root / mutation.relative_path
        original = target.read_text(encoding="utf-8")
        mutated = _mutate(original, mutation)
        try:
            compile(mutated, str(target), "exec")
        except SyntaxError as exc:
            invalid.append(f"{mutation.mutation_id}:{exc.msg}")
            continue
        try:
            target.write_text(mutated, encoding="utf-8")
            result = _run(root)
        finally:
            target.write_text(original, encoding="utf-8")
        if result.returncode == 0:
            survivors.append(mutation.mutation_id)
            print(f"SURVIVED {mutation.mutation_id}")
        else:
            print(f"KILLED   {mutation.mutation_id}")

    if invalid:
        print("invalid mutation(s): " + ", ".join(invalid), file=sys.stderr)
    if survivors:
        print("surviving mutation(s): " + ", ".join(survivors), file=sys.stderr)
    if invalid or survivors:
        return 1
    print(f"mutation campaign passed: {len(MUTATIONS)} killed, 0 survived")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
