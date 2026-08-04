from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = (
    ROOT
    / "daedalus"
    / "spine"
    / "promotion_recovery_consumption_effect_rows.py"
)
TESTS = (
    "tests/kernel/test_promotion_recovery_consumption_effect_rows.py",
    "tests/kernel/test_promotion_recovery_consumption_effect_rows_review.py",
)

MUTATIONS = (
    (
        "centralize-descriptors-early",
        'wiring="local_guards",',
        'wiring="central",',
        2,
        True,
    ),
    (
        "widen-open-effect",
        'effects=("filesystem_write",),',
        'effects=("filesystem_write", "repository_mutation"),',
        2,
        False,
    ),
    (
        "substitute-owner-recovery-guard",
        'else (_DECISION_GUARD, _STORE_GUARD)',
        'else ("promotion.owner_approval",)',
        1,
        False,
    ),
    (
        "skip-exact-materializer-check",
        "    _assert_exact_descriptors(descriptors)\n",
        "    # exact descriptor-set check removed\n",
        1,
        False,
    ),
    (
        "drop-materialized-anchors",
        "                anchors=anchors,\n",
        "                anchors=(),\n",
        1,
        False,
    ),
    (
        "accept-anchor-substitution",
        "        if self.anchors != expected_anchors:\n",
        "        if False:\n",
        1,
        False,
    ),
)


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write(
            "recovery-consumption effect-row mutation baseline failed\n"
        )
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    killed: list[str] = []
    try:
        for label, needle, replacement, expected_count, replace_all in MUTATIONS:
            count = original.count(needle)
            if count != expected_count:
                sys.stderr.write(
                    f"mutation {label} expected {expected_count} source seams, "
                    f"found {count}\n"
                )
                return 3
            mutated = (
                original.replace(needle, replacement)
                if replace_all
                else original.replace(needle, replacement, 1)
            )
            TARGET.write_text(mutated, encoding="utf-8")
            result = _run()
            if result.returncode == 0:
                sys.stderr.write(f"survived mutation: {label}\n")
                sys.stderr.write(result.stdout)
                sys.stderr.write(result.stderr)
                return 1
            killed.append(label)
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    print(
        "killed recovery-consumption effect-row mutations: "
        + ", ".join(killed)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
