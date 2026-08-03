#!/usr/bin/env python3
"""Run bounded mutations for persisted promotion authorization."""
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
        "bypass-persisted-consumption-verification",
        "        persisted = approval_ledger.verify_consumption(\n",
        "        persisted = consumed_approval if True else approval_ledger.verify_consumption(\n",
    ),
    Mutation(
        "accept-different-persisted-capability",
        "    if persisted != consumed_approval:\n",
        "    if False:\n",
    ),
    Mutation(
        "allow-empty-owner-keyring",
        "    if not isinstance(owner_keyring, Mapping) or not owner_keyring:\n",
        "    if False:\n",
    ),
)

FOCUSED_TESTS = (
    "tests/kernel/test_persisted_promotion_authorization.py",
    "tests/kernel/test_persisted_promotion_authorization_review.py",
    "tests/kernel/test_owner_approval.py",
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


def tail(result: subprocess.CompletedProcess[str], lines: int = 50) -> str:
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
    target = root / "daedalus/kernel/promotion.py"
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
        print("promotion source was not restored", file=sys.stderr)
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
