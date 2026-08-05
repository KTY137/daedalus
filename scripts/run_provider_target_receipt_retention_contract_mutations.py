"""Run bounded mutants against the receipt-retention guard contract."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/runtimes/provider_target_receipt_retention_contract.py"
TESTS = [
    "tests/runtimes/test_provider_target_receipt_retention_contract.py",
    "tests/runtimes/test_provider_target_receipt_retention_contract_review.py",
]
MUTANTS = {
    "claim_provider_execution": (
        '"provider_execution_allowed": False,',
        '"provider_execution_allowed": True,',
    ),
    "claim_effect_started": (
        '"retention_effect_started": False,',
        '"retention_effect_started": True,',
    ),
    "claim_checkout_proof": (
        '"primary_checkout_disjointness_verified": False,',
        '"primary_checkout_disjointness_verified": True,',
    ),
    "permit_subclass_receipt": (
        "if type(receipt) is not ProviderExecutableTargetVerificationReceipt:",
        "if not isinstance(receipt, ProviderExecutableTargetVerificationReceipt):",
    ),
    "permit_missing_kill_switch": (
        "if not execution.kill_switch_ref or not effect_lease.effect_scope.kill_switch_ref:",
        "if False and (not execution.kill_switch_ref or not effect_lease.effect_scope.kill_switch_ref):",
    ),
    "reuse_provider_lease": (
        "if effect_lease.digest == receipt.lease_sha256:",
        "if False and effect_lease.digest == receipt.lease_sha256:",
    ),
    "ignore_subject_substitution": (
        '"subject": (authority.subject, expected_subject),',
        '"subject": (expected_subject, expected_subject),',
    ),
    "extend_authority_ttl": (
        "if expires - issued > _MAX_AUTHORITY_TTL:",
        "if expires - issued > _MAX_AUTHORITY_TTL * 10:",
    ),
    "disable_path_overlap": (
        "left_path == right_path",
        "False",
    ),
}


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    survivors: list[str] = []
    try:
        for name, (old, new) in MUTANTS.items():
            if original.count(old) != 1:
                raise RuntimeError(f"mutation seam {name} is not unique")
            TARGET.write_text(original.replace(old, new, 1), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *TESTS],
                cwd=ROOT,
                env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
                check=False,
            )
            if completed.returncode == 0:
                survivors.append(name)
    finally:
        TARGET.write_text(original, encoding="utf-8")
    if survivors:
        print("surviving mutants: " + ", ".join(survivors), file=sys.stderr)
        return 1
    print(f"killed {len(MUTANTS)} bounded mutants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
