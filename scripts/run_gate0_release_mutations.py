#!/usr/bin/env python3
"""Run the bounded authenticated Gate-0 release mutation campaign."""
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
        "skip-trust-bundle-authentication",
        "daedalus/gates/release.py",
        "    verify_evidence_trust_bundle(\n",
        "    if False:\n        verify_evidence_trust_bundle(\n",
    ),
    Mutation(
        "trust-caller-security-claim",
        "daedalus/gates/release.py",
        "security_claimed = not local_boundary_blockers and not security_evidence_blockers",
        "security_claimed = local_report.security_boundary_claimed",
    ),
    Mutation(
        "confuse-report-artifact-with-inner-identity",
        "daedalus/gates/release.py",
        "elif retained_report.content_sha256 != mechanical_artifact_sha:\n        evidence_blockers.add(\"assembly:gate-report-artifact-mismatch\")",
        "elif retained_report.content_sha256 != mechanical_sha:\n        evidence_blockers.add(\"assembly:gate-report-artifact-mismatch\")",
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
        "accept-expanded-release-provenance",
        "daedalus/gates/release.py",
        "if self.provenance.input_digests != expected_inputs:",
        "if not set(expected_inputs).issubset(self.provenance.input_digests):",
    ),
    Mutation(
        "accept-noncanonical-release-wire",
        "daedalus/gates/release.py",
        "if original_wire != value.to_dict():",
        "if False:",
    ),
    Mutation(
        "skip-retained-release-reconstruction",
        "daedalus/gates/release_verifier.py",
        "if reconstructed.to_dict() != release.to_dict():",
        "if False:",
    ),
    Mutation(
        "skip-current-release-blockers",
        "daedalus/gates/release_verifier.py",
        "blockers.update(current_projection.blockers)",
        "blockers.update(())",
    ),
    Mutation(
        "ignore-trust-bundle-substitution",
        "daedalus/gates/release_verifier.py",
        "if release.evidence_trust_bundle_sha256 != trust_bundle.digest:",
        "if False:",
    ),
)

FOCUSED_TESTS = (
    "tests/gates/test_gate_report.py",
    "tests/gates/test_evidence_trust_bundle.py",
    "tests/gates/test_evidence_trust_bundle_review.py",
    "tests/gates/test_gate0_release_assembly.py",
    "tests/gates/test_gate0_release_verifier.py",
    "tests/gates/test_gate0_release_review.py",
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
