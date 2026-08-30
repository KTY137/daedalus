# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "daedalus" / "runtimes" / "provider_observation_store_contract.py"
TESTS = (
    "tests/runtimes/test_provider_observation_store_contract.py",
    "tests/runtimes/test_provider_observation_store_contract_review.py",
)
MUTATIONS = (
    (
        "accept-operation-entrypoint-mismatch",
        "            if self.entrypoint_id != expected_entrypoint:\n                raise ProviderObservationStoreContractBindingError(\n                    \"store operation entrypoint does not match operation\"\n                )\n",
        "            if False:  # mutant: accept operation/entrypoint mismatch\n                raise ProviderObservationStoreContractBindingError(\n                    \"store operation entrypoint does not match operation\"\n                )\n",
    ),
    (
        "accept-store-write-lease-mismatch",
        "    if mismatches:\n        raise ProviderObservationStoreContractBindingError(\n            \"store write lease/execution mismatch: \" + \", \".join(mismatches)\n        )\n",
        "    if False:  # mutant: accept store lease/execution mismatch\n        raise ProviderObservationStoreContractBindingError(\n            \"store write lease/execution mismatch: \" + \", \".join(mismatches)\n        )\n",
    ),
    (
        "accept-unrelated-store-effect-scope",
        "    if (\n        execution.egress_endpoints\n        or execution.tools\n        or execution.secret_refs\n        or execution.max_cost_microusd\n    ):\n",
        "    if False:  # mutant: accept unrelated effect scope\n",
    ),
    (
        "accept-provider-start-receipt-digest-mismatch",
        "    if receipt.receipt_sha256 != canonical_sha(expected_body):\n",
        "    if False:  # mutant: accept provider start receipt tamper\n",
    ),
    (
        "accept-incomplete-bind-runtime-authority",
        "        elif any(value is None for value in provider_fields):\n",
        "        elif False:  # mutant: accept incomplete bind authority\n",
    ),
    (
        "accept-store-authority-signature-mismatch",
        "    if not hmac.compare_digest(authority.signature_sha256, expected_signature):\n",
        "    if False:  # mutant: accept authority signature mismatch\n",
    ),
    (
        "accept-expired-store-authority",
        "    if instant < issued or instant >= expires:\n",
        "    if False:  # mutant: accept authority outside validity window\n",
    ),
    (
        "skip-guard-authority-verification",
        "    verify_provider_observation_store_operation_authority(\n        authority,\n        expected_authority_id=expected_authority_id,\n        authority_keyring=authority_keyring,\n        expected_subject=expected_subject,\n        at=at,\n    )\n",
        "    pass  # mutant: emit allowed decision without verification\n",
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
    original = SOURCE.read_text(encoding="utf-8")
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("baseline failed before store-contract mutations\n")
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
            SOURCE.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                survivors.append(name)
                sys.stderr.write(f"SURVIVED: {name}\n")
            else:
                print(f"killed: {name}")
            SOURCE.write_text(original, encoding="utf-8")
    finally:
        SOURCE.write_text(original, encoding="utf-8")

    if survivors:
        sys.stderr.write("surviving mutations: " + ", ".join(survivors) + "\n")
        return 1
    print(f"all {len(MUTATIONS)} store-contract mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
