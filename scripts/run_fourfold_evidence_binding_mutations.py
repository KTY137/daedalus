#!/usr/bin/env python3
"""Run bounded mutations against the Fourfold-to-trust evidence bridge."""
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
        "allow-candidate-locator-substitution",
        "        if _locator_sha256(candidate_locator) != candidate_sha:\n",
        "        if False:\n",
    ),
    Mutation(
        "allow-snapshot-candidate-repackaging",
        "    if candidate_sha not in snapshot.provenance.input_digests:\n",
        "    if False:\n",
    ),
    Mutation(
        "allow-partial-snapshot-as-gate-evidence",
        "    if incomplete:\n",
        "    if False:\n",
    ),
    Mutation(
        "allow-foreign-evidence-subject",
        "    if packet.subject_sha256 != expectation.candidate_artifact_sha256:\n",
        "    if False:\n",
    ),
    Mutation(
        "allow-foreign-nomination-evidence",
        "    if nomination.evidence_packet_sha256 != packet.digest:\n",
        "    if False:\n",
    ),
    Mutation(
        "skip-canonical-evidence-reconstruction",
        "    rebuilt = EvidencePacket.from_dict(packet.to_dict())\n",
        "    rebuilt = packet\n",
    ),
)

FOCUSED_TESTS = (
    "tests/kernel/test_fourfold_evidence_owner_binding.py",
    "tests/kernel/test_fourfold_evidence_adversarial.py",
    "tests/kernel/test_fourfold_evidence_source_review.py",
)


def run_tests(root: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *FOCUSED_TESTS],
        cwd=root,
        env=env,
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
    target = root / "daedalus/kernel/fourfold_evidence.py"
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
        print("Fourfold evidence source was not restored", file=sys.stderr)
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
