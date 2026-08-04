from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "spine" / "promotion_effect_rows.py"
TESTS = (
    "tests/kernel/test_promotion_effect_rows.py",
    "tests/kernel/test_promotion_effect_rows_review.py",
    "tests/kernel/test_promotion_effect_inventory.py",
)
MUTATIONS = (
    (
        "premature-centralization",
        "\"wiring\": boundary.Wiring.LOCAL_GUARDS,",
        "\"wiring\": boundary.Wiring.CENTRAL,",
    ),
    (
        "omit-open-row",
        "        boundary.EntrypointSpec(\n            id=\"kernel.promotion_execution.open\",",
        "        boundary.EntrypointSpec(\n            id=\"kernel.promotion_execution.open.removed\",",
    ),
    (
        "stale-begin-effect-default",
        "    boundary.begin_effect.__kwdefaults__ = {\n        **(boundary.begin_effect.__kwdefaults__ or {}),\n        \"registry\": boundary.REGISTRY_BY_ID,\n    }\n",
        "    pass  # mutant leaves stale begin_effect registry\n",
    ),
    (
        "accept-partial-installation",
        "    if any(row is not None for row in present):\n",
        "    if all(row is not None for row in present):\n",
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
        sys.stderr.write("baseline failed before mutation campaign\n")
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
            TARGET.write_text(original.replace(needle, replacement, 1), encoding="utf-8")
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
    print(f"all {len(MUTATIONS)} promotion-row mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
