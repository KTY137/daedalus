"""Targeted mutations for exact durable fault-state verification."""
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
    "tests/gates/test_fault_matrix_contract_review.py",
)
MUTATIONS = (
    (
        "exact-marker-set-to-subset",
        "            and receipt.durable_markers == spec.expected_durable_markers\n",
        "            and set(spec.expected_durable_markers).issubset(receipt.durable_markers)\n",
    ),
    (
        "exact-durable-claim-escalation",
        '            "exact_durable_states_verified": passed,\n',
        '            "exact_durable_states_verified": True,\n',
    ),
)


def _run(mutated_source: str, name: str) -> None:
    with tempfile.TemporaryDirectory(
        prefix=f"daedalus-fault-durable-{name}-"
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
    print(f"killed {len(MUTATIONS)} exact durable-state mutants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
