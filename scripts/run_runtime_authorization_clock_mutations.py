#!/usr/bin/env python3
"""Run bounded mutations against runtime facade clock ownership."""
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
        "reintroduce-caller-verification-clock",
        "daedalus/kernel/runtime_effects.py",
        "    def verify(self) -> RuntimeTrustRecord:\n",
        "    def verify(self, *, now: datetime | None = None) -> RuntimeTrustRecord:\n",
    ),
    Mutation(
        "broker-supplies-verification-clock",
        "daedalus/runtimes/broker.py",
        "        authorization.verify()\n",
        "        authorization.verify(now=_utc_now())\n",
    ),
)

FOCUSED_TESTS = (
    "tests/kernel/test_runtime_effect_admission.py",
    "tests/kernel/test_runtime_terminal_capability.py",
    "tests/kernel/test_runtime_authorization_clock.py",
    "tests/runtimes/test_runtime_provider_broker.py",
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


def _tail(result: subprocess.CompletedProcess[str], lines: int = 50) -> str:
    combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return "\n".join(combined.splitlines()[-lines:])


def _mutate(source: str, mutation: Mutation) -> str:
    count = source.count(mutation.original)
    if mutation.mutation_id == "broker-supplies-verification-clock":
        if count != 2:
            raise RuntimeError(
                f"{mutation.mutation_id}: expected two clockless broker seams, found {count}"
            )
        return source.replace(mutation.original, mutation.replacement)
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

    dirty = [
        mutation.relative_path
        for mutation in MUTATIONS
        if not (root / mutation.relative_path).is_file()
    ]
    if dirty:
        print("mutation targets disappeared: " + ", ".join(dirty), file=sys.stderr)
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
