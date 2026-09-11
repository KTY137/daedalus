"""Bounded mutation campaign for receipt-retention recovery decisions."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = Path(
    "daedalus/runtimes/provider/target_receipt_retention_recovery.py"
)
TESTS = (
    "tests/runtimes/test_provider_target_receipt_retention_recovery.py",
    "tests/runtimes/test_provider_target_receipt_retention_recovery_hardening.py",
    "tests/runtimes/test_provider_target_receipt_retention_recovery_review.py",
)

MUTATIONS = (
    (
        "exact-admission-type-bypass",
        "    if type(admission) is not ProviderTargetReceiptRetentionAdmissionReceipt:\n",
        "    if False:\n",
    ),
    (
        "commit-revision-width-bypass",
        "    if len(revision) != 40:\n",
        "    if False:\n",
    ),
    (
        "stale-revision-bypass",
        "    if admission.source_revision != revision:\n",
        "    if False:\n",
    ),
    (
        "state-action-binding-bypass",
        "        if type(self.decision) is not str or self.decision != expected_decision:\n",
        "        if False:\n",
    ),
    (
        "started-start-receipt-bypass",
        "                self.start_receipt_sha256 is None\n",
        "                False\n",
    ),
    (
        "started-decision-substitution",
        '    "started": "manual_reconciliation_required",\n',
        '    "started": "request_fresh_start_authorization",\n',
    ),
    (
        "final-snapshot-fence-bypass",
        "        final_snapshot != snapshot\n",
        "        False\n",
    ),
    (
        "persisted-state-claim-escalation",
        '            "admission_identity_bound": True,\n'
        '            "persisted_state_reverified": False,\n'
        '            "manual_reconciliation_required": reconciliation,\n',
        '            "admission_identity_bound": True,\n'
        '            "persisted_state_reverified": True,\n'
        '            "manual_reconciliation_required": reconciliation,\n',
    ),
    (
        "automatic-reexecution-claim-escalation",
        '            "terminal_state_observed": terminal,\n'
        '            "automatic_reexecution_allowed": False,\n'
        '            "effect_start_authorized": False,\n',
        '            "terminal_state_observed": terminal,\n'
        '            "automatic_reexecution_allowed": True,\n'
        '            "effect_start_authorized": False,\n',
    ),
    (
        "effect-start-claim-escalation",
        '            "terminal_state_observed": terminal,\n'
        '            "automatic_reexecution_allowed": False,\n'
        '            "effect_start_authorized": False,\n'
        '            "retention_write_authorized": False,\n',
        '            "terminal_state_observed": terminal,\n'
        '            "automatic_reexecution_allowed": False,\n'
        '            "effect_start_authorized": True,\n'
        '            "retention_write_authorized": False,\n',
    ),
    (
        "retention-write-claim-escalation",
        '            "terminal_state_observed": terminal,\n'
        '            "automatic_reexecution_allowed": False,\n'
        '            "effect_start_authorized": False,\n'
        '            "retention_write_authorized": False,\n'
        '            "effect_terminalization_authorized": False,\n',
        '            "terminal_state_observed": terminal,\n'
        '            "automatic_reexecution_allowed": False,\n'
        '            "effect_start_authorized": False,\n'
        '            "retention_write_authorized": True,\n'
        '            "effect_terminalization_authorized": False,\n',
    ),
    (
        "terminalization-claim-escalation",
        '            "terminal_state_observed": terminal,\n'
        '            "automatic_reexecution_allowed": False,\n'
        '            "effect_start_authorized": False,\n'
        '            "retention_write_authorized": False,\n'
        '            "effect_terminalization_authorized": False,\n'
        '            "canonical_entrypoint_registered": False,\n',
        '            "terminal_state_observed": terminal,\n'
        '            "automatic_reexecution_allowed": False,\n'
        '            "effect_start_authorized": False,\n'
        '            "retention_write_authorized": False,\n'
        '            "effect_terminalization_authorized": True,\n'
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
    print(f"killed {len(MUTATIONS)} receipt-retention recovery mutants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
