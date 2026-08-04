from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kairos" / "promotion_entrypoint.py"
TESTS = (
    "tests/kernel/test_promotion_public_entrypoint.py",
    "tests/kernel/test_promotion_public_entrypoint_review.py",
)
MUTATIONS = (
    (
        "skip-lifecycle-delegation",
        "    return promote_candidates_with_effect_lifecycle(\n",
        "    return {} if True else promote_candidates_with_effect_lifecycle(\n",
    ),
    (
        "drop-effect-capability-binding",
        "        promotion_effect_capability=promotion_effect_capability,\n",
        "        promotion_effect_capability=None,  # mutant\n",
    ),
    (
        "drop-target-revision-subject",
        "        target_ref=target_ref,\n",
        "        target_ref=None,  # mutant\n",
    ),
    (
        "add-untyped-keyword-smuggling",
        "    cancel: Any = None,\n) -> dict[str, Any]:\n",
        "    cancel: Any = None,\n    **kwargs: Any,  # mutant\n) -> dict[str, Any]:\n",
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
        sys.stderr.write("baseline failed before promotion-entrypoint mutations\n")
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    survivors: list[str] = []
    try:
        for name, needle, replacement in MUTATIONS:
            count = original.count(needle)
            if count != 1:
                sys.stderr.write(
                    f"mutation {name} expected one source seam, found {count}\n"
                )
                return 3
            TARGET.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                survivors.append(name)
                sys.stderr.write(f"SURVIVED: {name}\n")
            else:
                print(f"killed: {name}")
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    if survivors:
        sys.stderr.write("surviving mutations: " + ", ".join(survivors) + "\n")
        return 1
    print(f"all {len(MUTATIONS)} promotion-entrypoint mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
