"""Bounded mutation campaign for completed receipt-retention evidence."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = Path(
    "daedalus/runtimes/"
    "provider_target_receipt_retention_completed_evidence.py"
)
TESTS = (
    "tests/runtimes/test_provider_target_receipt_retention_completed_evidence.py",
    "tests/runtimes/"
    "test_provider_target_receipt_retention_completed_evidence_hardening.py",
    "tests/runtimes/"
    "test_provider_target_receipt_retention_completed_evidence_review.py",
)

MUTATIONS = (
    (
        "exact-subject-type-bypass",
        "        if type(value) is not expected:\n",
        "        if False:\n",
    ),
    (
        "commit-revision-width-bypass",
        "    if len(revision) != 40:\n",
        "    if False:\n",
    ),
    (
        "artifact-hardlink-bypass",
        "        if info.st_nlink != 1:\n",
        "        if False:\n",
    ),
    (
        "admission-live-identity-binding-bypass",
        "        if expected[key] != observed[key]:\n",
        "        if False:\n",
    ),
    (
        "admission-root-containment-bypass",
        "    if root_path not in event_path.parents or root_path not in cas_path.parents:\n",
        "    if False:\n",
    ),
    (
        "completed-admission-bypass",
        '    if admission.execution_state != "COMPLETED":\n',
        "    if False:\n",
    ),
    (
        "recovery-admission-binding-bypass",
        "    if recovery.admission_sha256 != admission.digest:\n",
        "    if False:\n",
    ),
    (
        "provider-receipt-binding-bypass",
        "    if admission.provider_target_receipt_sha256 != receipt.digest:\n",
        "    if False:\n",
    ),
    (
        "authentication-topology-fence-bypass",
        "        topology_mid != topology_before\n",
        "        False\n",
    ),
    (
        "retained-read-topology-fence-bypass",
        "        topology_after != topology_before\n",
        "        False\n",
    ),
    (
        "event-state-double-read-bypass",
        "    if intent != final_intent or final_intent.state != STATE_COMPLETED:\n",
        "    if False:\n",
    ),
    (
        "max-source-shape-bypass",
        "    if (\n"
        "        isinstance(max_source_bytes, bool)\n"
        "        or not isinstance(max_source_bytes, int)\n"
        "        or max_source_bytes < 1\n"
        "    ):\n",
        "    if False:\n",
    ),
    (
        "admission-topology-claim-removal",
        '            "admission_topology_bound": True,\n',
        '            "admission_topology_bound": False,\n',
    ),
    (
        "stable-topology-claim-removal",
        '            "retention_topology_stable": True,\n',
        '            "retention_topology_stable": False,\n',
    ),
    (
        "closure-claim-escalation",
        "            **{field: False for field in _FALSE_CLAIMS},\n",
        '            **{field: field == "closed" for field in _FALSE_CLAIMS},\n',
    ),
)


def _run(mutated_source: str, name: str) -> None:
    with tempfile.TemporaryDirectory(prefix=f"daedalus-{name}-") as directory:
        sandbox = Path(directory)
        shutil.copytree(ROOT / "daedalus", sandbox / "daedalus")
        target = sandbox / MODULE
        target.write_text(mutated_source, encoding="utf-8")
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
    print(f"killed {len(MUTATIONS)} completed-retention evidence mutants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
