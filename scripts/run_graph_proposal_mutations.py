#!/usr/bin/env python3
"""Run a bounded security mutation campaign for graph proposals."""
from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from pathlib import Path


@dataclasses.dataclass(frozen=True)
class Mutation:
    mutation_id: str
    original: str
    replacement: str


MUTATIONS = (
    Mutation(
        "ignore-stale-base-snapshot",
        "        if proposal.base_snapshot_sha256 != snapshot.digest:\n",
        "        if False:\n",
    ),
    Mutation(
        "trust-unverified-operation-evidence",
        "        if not set(operation.evidence_sha256s).issubset(verified):\n",
        "        if False:\n",
    ),
    Mutation(
        "ignore-source-node-scope",
        "        if operation.source_node_id not in scope.node_ids:\n",
        "        if False:\n",
    ),
    Mutation(
        "accept-substituted-binding-digest",
        "        operation.binding_sha256 == binding.digest\n",
        "        True\n",
    ),
    Mutation(
        "trust-report-owned-verifier",
        "    if report.verifier_id != verifier:\n",
        "    if False:\n",
    ),
    Mutation(
        "normalize-noncanonical-proposal-wire",
        "    if dict(payload) != value.to_dict():\n        raise ValueError(\"graph proposal wire is not canonical\")\n",
        "    if False:\n        raise ValueError(\"graph proposal wire is not canonical\")\n",
    ),
)

FOCUSED_TESTS = (
    "tests/twin/test_graph_proposals.py",
    "tests/twin/test_graph_proposal_review.py",
)


def run_tests(root: Path) -> subprocess.CompletedProcess[str]:
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


def tail(result: subprocess.CompletedProcess[str], lines: int = 60) -> str:
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return "\n".join(combined.splitlines()[-lines:])


def mutate_once(source: str, mutation: Mutation) -> str:
    count = source.count(mutation.original)
    if count != 1:
        raise RuntimeError(
            f"{mutation.mutation_id}: expected one mutation seam, found {count}"
        )
    return source.replace(mutation.original, mutation.replacement, 1)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    target = root / "daedalus/twin/proposals.py"

    baseline = run_tests(root)
    if baseline.returncode != 0:
        print("baseline focused suite failed; mutation evidence is invalid", file=sys.stderr)
        print(tail(baseline), file=sys.stderr)
        return 2

    original_source = target.read_text(encoding="utf-8")
    survivors: list[str] = []
    invalid: list[str] = []

    for mutation in MUTATIONS:
        mutated = mutate_once(original_source, mutation)
        try:
            compile(mutated, str(target), "exec")
        except SyntaxError as exc:
            invalid.append(f"{mutation.mutation_id}:{exc.msg}")
            continue
        try:
            target.write_text(mutated, encoding="utf-8")
            result = run_tests(root)
        finally:
            target.write_text(original_source, encoding="utf-8")
        if result.returncode == 0:
            survivors.append(mutation.mutation_id)
            print(f"SURVIVED {mutation.mutation_id}")
        else:
            print(f"KILLED   {mutation.mutation_id}")

    if target.read_text(encoding="utf-8") != original_source:
        print("proposal source was not restored", file=sys.stderr)
        return 3
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
