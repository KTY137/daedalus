"""Bounded mutation campaign for receipt-retention admission."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = Path(
    "daedalus/runtimes/provider_target_receipt_retention_admission.py"
)
TESTS = (
    "tests/runtimes/test_provider_target_receipt_retention_admission.py",
    "tests/runtimes/test_provider_target_receipt_retention_admission_review.py",
)

MUTATIONS = (
    (
        "final-preflight-fence-bypass",
        "    final_preflight = _replay_preflight(\n",
        "    final_preflight = preflight or _replay_preflight(\n",
    ),
    (
        "final-topology-fence-bypass",
        "    final_topology = _verify_topology(\n",
        "    final_topology = topology or _verify_topology(\n",
    ),
    (
        "guard-equality-bypass",
        "    if guards[0] != expected:\n",
        "    if False:\n",
    ),
    (
        "exact-replay-type-bypass",
        "    if replay is not None and type(replay) is not EffectExecutionReplaySnapshot:\n",
        "    if False:\n",
    ),
    (
        "single-link-identity-bypass",
        "        if info.st_nlink != 1:\n",
        "        if False:\n",
    ),
    (
        "concrete-cas-binding-bypass",
        "    if not _same_identity(cas, expected_cas):\n",
        "    if False:\n",
    ),
    (
        "primary-retention-overlap-bypass",
        "    if _overlap(primary[0], root[0]):\n",
        "    if False:\n",
    ),
    (
        "pairwise-store-disjointness-bypass",
        "            if _overlap(left[0], right[0]) or _same_identity(left, right):\n",
        "            if False:\n",
    ),
    (
        "preflight-subject-binding-bypass",
        "        preflight.retention_execution_request_sha256 != execution.digest\n",
        "        False\n",
    ),
    (
        "final-preflight-digest-bypass",
        "    if final_preflight.digest != preflight.digest:\n",
        "    if False:\n",
    ),
    (
        "write-claim-escalation",
        '            "retention_effect_terminal": terminal,\n'
        '            "retention_write_performed": False,\n',
        '            "retention_effect_terminal": terminal,\n'
        '            "retention_write_performed": True,\n',
    ),
    (
        "automatic-reexecution-claim-escalation",
        '            "retention_write_performed": False,\n'
        '            "automatic_reexecution_allowed": False,\n'
        '            "canonical_entrypoint_registered": False,\n',
        '            "retention_write_performed": False,\n'
        '            "automatic_reexecution_allowed": True,\n'
        '            "canonical_entrypoint_registered": False,\n',
    ),
    (
        "closure-claim-escalation",
        '            "canonical_entrypoint_registered": False,\n'
        '            "gate_transition_authorized": False,\n'
        '            "closed": False,\n'
        "        }\n\n    @classmethod\n",
        '            "canonical_entrypoint_registered": False,\n'
        '            "gate_transition_authorized": False,\n'
        '            "closed": True,\n'
        "        }\n\n    @classmethod\n",
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
    print(f"killed {len(MUTATIONS)} receipt-retention admission mutants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
