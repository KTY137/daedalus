from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "daedalus" / "runtimes" / "provider" / "invocation_authority.py"
TESTS = (
    "tests/runtimes/test_provider_invocation_authority.py",
    "tests/runtimes/test_provider_invocation_authority_review.py",
)
MUTATIONS = (
    (
        "accept-cross-authority-subject-mismatch",
        "        if mismatches:\n            raise ProviderInvocationAuthorityBindingError(\n                \"invocation-observation authority subject mismatch: \"\n                + \", \".join(mismatches)\n            )\n",
        "        if False:  # mutant: accept cross-authority mismatch\n            raise ProviderInvocationAuthorityBindingError(\n                \"invocation-observation authority subject mismatch: \"\n                + \", \".join(mismatches)\n            )\n",
    ),
    (
        "accept-composite-signature-mismatch",
        "    if not hmac.compare_digest(authority.signature_sha256, expected_signature):\n",
        "    if False:  # mutant: accept composite signature mismatch\n",
    ),
    (
        "ignore-expected-invocation-subject",
        "        \"invocation_subject\": (\n            authority.invocation_subject,\n            invocation_subject,\n        ),\n",
        "        \"invocation_subject\": (\n            invocation_subject,\n            invocation_subject,  # mutant\n        ),\n",
    ),
    (
        "ignore-expected-contract-id",
        "        \"invocation_contract_id\": (\n            authority.invocation_contract_id,\n            expected_contract_id,\n        ),\n",
        "        \"invocation_contract_id\": (\n            expected_contract_id,\n            expected_contract_id,  # mutant\n        ),\n",
    ),
    (
        "ignore-expected-registry-digest",
        "        \"invocation_registry_sha256\": (\n            authority.invocation_registry_sha256,\n            expected_registry,\n        ),\n",
        "        \"invocation_registry_sha256\": (\n            expected_registry,\n            expected_registry,  # mutant\n        ),\n",
    ),
    (
        "detach-registry-from-contract-digest",
        "                \"invocation_registry_sha256\": self.invocation_registry_sha256,\n",
        "                \"invocation_registry_sha256\": \"0\" * 64,  # mutant\n",
    ),
    (
        "accept-nonexact-outer-fields",
        "        if not isinstance(payload, Mapping) or set(payload) != expected:\n",
        "        if not isinstance(payload, Mapping) or False:  # mutant\n",
    ),
    (
        "accept-authority-subclasses",
        "    if type(authority) is not ProviderInvocationObservationAuthority:\n",
        "    if not isinstance(authority, ProviderInvocationObservationAuthority):  # mutant\n",
    ),
    (
        "remove-keyring-normalization",
        "        authority_rows = dict(\n            _normalize_keyring(authority_keyring, label=\"authority_keyring\")\n        )\n",
        "        authority_rows = dict(authority_keyring)  # mutant\n",
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
        sys.stderr.write("baseline failed before invocation-authority mutations\n")
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
    print(f"all {len(MUTATIONS)} invocation-authority mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
