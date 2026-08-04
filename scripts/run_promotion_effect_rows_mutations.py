from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "spine" / "promotion_effect_rows.py"
TESTS = (
    "tests/kernel/test_promotion_effect_rows.py",
    "tests/kernel/test_promotion_effect_rows_review.py",
)

MUTATIONS = (
    (
        "centralize-descriptors-early",
        'wiring="local_guards",',
        'wiring="central",',
        3,
    ),
    (
        "widen-open-effect",
        'effects=("filesystem_write",),',
        'effects=("process_spawn",),',
        1,
    ),
    (
        "remove-intent-ledger-guard",
        'guard_contracts=("spine.intent_ledger",),',
        "guard_contracts=(),",
        1,
    ),
    (
        "skip-exact-descriptor-set-check",
        "    _assert_descriptor_set(descriptors)\n",
        "    # exact descriptor-set check removed\n",
        1,
    ),
    (
        "drop-ledger-open-row",
        "    PromotionExecutionRowDescriptor(\n        entrypoint_id=\"kernel.promotion_execution.open\",",
        "    # open row removed\n    PromotionExecutionRowDescriptor(\n        entrypoint_id=\"kernel.promotion_execution.begin\",",
        1,
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
        sys.stderr.write("promotion effect-row mutation baseline failed\n")
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    killed: list[str] = []
    try:
        for label, needle, replacement, expected_count in MUTATIONS:
            count = original.count(needle)
            if count != expected_count:
                sys.stderr.write(
                    f"mutation {label} expected {expected_count} source seams, "
                    f"found {count}\n"
                )
                return 3
            mutated = original
            if label == "centralize-descriptors-early":
                mutated = mutated.replace(needle, replacement)
            else:
                mutated = mutated.replace(needle, replacement, 1)
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

    print("killed promotion effect-row mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
