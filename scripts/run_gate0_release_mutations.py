#!/usr/bin/env python3
"""Run the bounded G0-RPT-08B release-report mutation campaign.

The campaign first requires the unmodified focused suite to pass. Each mutant
is then applied alone, compiled, exercised in a fresh pytest subprocess, and
fully restored before the next mutant. A green mutant is a campaign failure.
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
        "trust-caller-security-claim",
        "daedalus/gates/release.py",
        "security_claimed = not local_boundary_blockers and not security_evidence_blockers",
        "security_claimed = local_report.security_boundary_claimed",
    ),
    Mutation(
        "ignore-mechanical-report-artifact-mismatch",
        "daedalus/gates/release.py",
        "elif retained_report.content_sha256 != mechanical_sha:\n        evidence_blockers.add(\"assembly:gate-report-artifact-mismatch\")",
        "elif False:\n        evidence_blockers.add(\"assembly:gate-report-artifact-mismatch\")",
    ),
    Mutation(
        "drop-owner-decision-blockers",
        "daedalus/gates/release.py",
        "exact_head_blockers=tuple(sorted(evidence_blockers)),",
        "exact_head_blockers=tuple(sorted(value for value in evidence_blockers if not value.startswith(_OWNER_EVIDENCE_PREFIX))),",
    ),
    Mutation(
        "accept-claimed-release-closed",
        "daedalus/gates/release.py",
        "if claimed_closed is not value.closed:",
        "if False:",
    ),
    Mutation(
        "skip-retained-release-reconstruction",
        "daedalus/gates/release_verifier.py",
        "if reconstructed.to_dict() != release.to_dict():",
        "if False:",
    ),
    Mutation(
        "skip-current-evidence-blockers",
        "daedalus/gates/release_verifier.py",
        "blockers.update(current_projection.blockers)",
        "blockers.update(())",
    ),
)

FOCUSED_TESTS = (
    "tests/gates/test_gate0_release_assembly.py",
    "tests/gates/test_gate0_release_verifier.py",
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


def output_tail(result: subprocess.CompletedProcess[str], *, lines: int = 40) -> str:
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
