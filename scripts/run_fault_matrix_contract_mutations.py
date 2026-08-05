"""Bounded mutation campaign for the canonical Gate-0 fault matrix contract."""
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
    "tests/gates/test_fault_matrix_contract.py",
    "tests/gates/test_fault_matrix_contract_schema.py",
)

MUTATIONS = (
    (
        "manifest-source-revision-bypass",
        "    if manifest.source_revision != source_revision:\n",
        "    if False:\n",
    ),
    (
        "missing-inventory-bypass",
        "    missing = tuple(sorted(expected_ids - observed_ids))\n",
        "    missing = ()\n",
    ),
    (
        "extra-inventory-bypass",
        "    extra = tuple(sorted(observed_ids - expected_ids))\n",
        "    extra = ()\n",
    ),
    (
        "scenario-spec-binding-bypass",
        "            receipt.scenario_spec_sha256 == spec.digest\n",
        "            True\n",
    ),
    (
        "checkout-mutation-bypass",
        "            and receipt.primary_checkout_before_sha256\n            == receipt.primary_checkout_after_sha256\n",
        "            and True\n",
    ),
    (
        "automatic-reexecution-observation-bypass",
        "            and receipt.automatic_reexecution_performed is False\n",
        "            and True\n",
    ),
    (
        "llm-evidence-observation-bypass",
        "            and receipt.llm_evidence_used is False\n",
        "            and True\n",
    ),
    (
        "unconditional-pass",
        '    status = "passed" if not blockers else "failed"\n',
        '    status = "passed"\n',
    ),
    (
        "failed-evidence-projection-bypass",
        '        if self.status != "passed":\n',
        "        if False:\n",
    ),
    (
        "manifest-evidence-binding-bypass",
        "            manifest.matrix_id != self.matrix_id\n",
        "            False\n",
    ),
    (
        "scenario-auto-reexecution-claim-escalation",
        '            "automatic_reexecution_allowed": False,\n',
        '            "automatic_reexecution_allowed": True,\n',
    ),
    (
        "manifest-closure-claim-escalation",
        '            "inventory_complete_claimed": False,\n            "faults_executed": False,\n            "gate_transition_authorized": False,\n            "closed": False,\n',
        '            "inventory_complete_claimed": False,\n            "faults_executed": False,\n            "gate_transition_authorized": False,\n            "closed": True,\n',
    ),
    (
        "verification-closure-claim-escalation",
        '            "gate_transition_authorized": False,\n            "closed": False,\n        }\n\n    def to_fault_matrix_evidence',
        '            "gate_transition_authorized": False,\n            "closed": True,\n        }\n\n    def to_fault_matrix_evidence',
    ),
)


def _run(mutated_source: str, name: str) -> None:
    with tempfile.TemporaryDirectory(prefix=f"daedalus-fault-matrix-{name}-") as directory:
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
    print(f"killed {len(MUTATIONS)} canonical fault-matrix mutants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
