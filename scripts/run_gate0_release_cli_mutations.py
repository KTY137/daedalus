#!/usr/bin/env python3
"""Run bounded mutations against strict Gate-0 release loading and verification.

The unmodified focused suite must pass first. Each mutant is applied alone in a
fresh pytest subprocess and restored before the next one. Invalid seams,
survivors, or dirty restoration fail the campaign.
"""
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
        "accept-duplicate-json-keys",
        "daedalus/gates/release_io.py",
        "object_pairs_hook=_reject_duplicate_keys,",
        "object_pairs_hook=dict,",
    ),
    Mutation(
        "accept-normalized-release-wire",
        "daedalus/gates/release_io.py",
        "if wire != value.to_dict():\n        raise ValueError(\"Gate-0 release report must use its exact canonical wire form\")",
        "if False:\n        raise ValueError(\"Gate-0 release report must use its exact canonical wire form\")",
    ),
    Mutation(
        "accept-normalized-mechanical-wire",
        "daedalus/gates/release_io.py",
        "if wire != value.to_dict():\n        raise ValueError(\"mechanical Gate report must use its exact canonical wire form\")",
        "if False:\n        raise ValueError(\"mechanical Gate report must use its exact canonical wire form\")",
    ),
    Mutation(
        "ignore-selected-secret-environment",
        "daedalus/gates/release_cli.py",
        "secret = os.environ.get(args.collector_secret_env)",
        "secret = \"x\" * 32",
    ),
    Mutation(
        "ignore-adopted-workflow-paths",
        "daedalus/gates/release_cli.py",
        "expected_workflow_paths=workflows,",
        "expected_workflow_paths={item.workflow_id: item.repository_path for item in trust_bundle.workflow_anchors},",
    ),
    Mutation(
        "return-success-with-blockers",
        "daedalus/gates/release_cli.py",
        "return 0 if not blockers else 1",
        "return 0",
    ),
    Mutation(
        "claim-trusted-with-blockers",
        "daedalus/gates/release_cli.py",
        '"trusted": not blockers,',
        '"trusted": True,',
    ),
    Mutation(
        "return-success-on-malformed-input",
        "daedalus/gates/release_cli.py",
        "        return 2\n",
        "        return 0\n",
    ),
)

FOCUSED_TESTS = (
    "tests/gates/test_gate0_release_assembly.py",
    "tests/gates/test_gate0_release_verifier.py",
    "tests/gates/test_gate0_release_review.py",
    "tests/gates/test_gate0_release_io.py",
    "tests/gates/test_gate0_mechanical_report_io.py",
    "tests/gates/test_gate0_release_cli.py",
    "tests/gates/test_gate0_release_cli_workflows.py",
    "tests/gates/test_gate0_release_cli_review.py",
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


def output_tail(result: subprocess.CompletedProcess[str], *, lines: int = 50) -> str:
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
    baseline = run_tests(root)
    if baseline.returncode != 0:
        print("baseline focused suite failed; mutation evidence is invalid", file=sys.stderr)
        print(output_tail(baseline), file=sys.stderr)
        return 2

    survivors: list[str] = []
    invalid: list[str] = []
    for mutation in MUTATIONS:
        target = root / mutation.relative_path
        original = target.read_text(encoding="utf-8")
        mutated = mutate_once(original, mutation)
        try:
            compile(mutated, str(target), "exec")
        except SyntaxError as exc:
            invalid.append(f"{mutation.mutation_id}:{exc.msg}")
            continue
        try:
            target.write_text(mutated, encoding="utf-8")
            result = run_tests(root)
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
