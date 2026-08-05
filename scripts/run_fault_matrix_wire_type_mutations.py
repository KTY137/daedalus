"""Targeted mutations for exact fault-contract wire scalar types."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = Path("daedalus/gates/fault_matrix.py")
TESTS = (
    "tests/gates/test_fault_matrix_exact_durable_state.py",
    "tests/gates/test_fault_matrix_wire_type_review.py",
)
MUTATIONS = (
    (
        "scenario-array-type-bypass",
        "        if any(type(payload[field]) is not list for field in array_fields):\n",
        "        if False:\n",
    ),
    (
        "verification-bool-type-bypass",
        "        if any(type(payload[field]) is not bool for field in bool_fields):\n",
        "        if False:\n",
    ),
    (
        "verification-failure-count-type-bypass",
        '        if type(payload["failure_count"]) is not int:\n',
        "        if False:\n",
    ),
)


def _run(mutated_source: str, name: str) -> None:
    with tempfile.TemporaryDirectory(
        prefix=f"daedalus-fault-wire-{name}-"
    ) as directory:
        sandbox = Path(directory)
        shutil.copytree(ROOT / "daedalus", sandbox / "daedalus")
        (sandbox / MODULE).write_text(mutated_source, encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(sandbox) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *TESTS],
            cwd=ROOT,
            env=env,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode == 0:
            raise SystemExit(f"mutant survived: {name}\n{result.stdout}")


def main() -> int:
    source = (ROOT / MODULE).read_text(encoding="utf-8")
    for name, old, new in MUTATIONS:
        count = source.count(old)
        if count != 1:
            raise SystemExit(f"mutation seam is not unique for {name}: {count}")
        _run(source.replace(old, new, 1), name)
    print(f"killed {len(MUTATIONS)} exact wire-type mutants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
