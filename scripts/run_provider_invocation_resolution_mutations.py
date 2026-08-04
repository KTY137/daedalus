from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "daedalus" / "runtimes" / "provider_invocation_resolution.py"
TESTS = (
    "tests/runtimes/test_provider_invocation_resolution.py",
    "tests/runtimes/test_provider_invocation_resolution_review.py",
)
MUTATIONS = (
    (
        "accept-signed-registry-digest-mismatch",
        "    if authority.invocation_registry_sha256 != manifest.digest:\n        raise ProviderInvocationResolutionBindingError(\n            \"signed invocation registry digest does not match manifest\"\n        )\n",
        "    if False:  # mutant: accept signed registry mismatch\n        raise ProviderInvocationResolutionBindingError(\n            \"signed invocation registry digest does not match manifest\"\n        )\n",
    ),
    (
        "skip-composite-authority-verification",
        "        verify_provider_invocation_observation_authority(\n            authority,\n",
        "        (lambda *args, **kwargs: None)(  # mutant\n            authority,\n",
    ),
    (
        "accept-unresolved-subject",
        "        descriptor = manifest.resolve(authority.invocation_subject)\n",
        "        descriptor = manifest.descriptors[0]  # mutant\n",
    ),
    (
        "detach-implementation-from-receipt",
        "        \"implementation_id\": descriptor.implementation_id,\n",
        "        \"implementation_id\": \"implementation.detached\",  # mutant\n",
    ),
    (
        "accept-receipt-digest-mismatch",
        "        if self.receipt_sha256 != expected:\n",
        "        if False:  # mutant: accept receipt digest mismatch\n",
    ),
    (
        "accept-naive-resolution-time",
        "    if value.tzinfo is None or value.utcoffset() is None:\n",
        "    if False:  # mutant: accept naive time\n",
    ),
    (
        "accept-retained-registry-mismatch",
        "    if authority.invocation_registry_sha256 != manifest.digest:\n        raise ProviderInvocationResolutionBindingError(\n            \"retained authority and registry digest do not match\"\n        )\n",
        "    if False:  # mutant: accept retained registry mismatch\n        raise ProviderInvocationResolutionBindingError(\n            \"retained authority and registry digest do not match\"\n        )\n",
    ),
    (
        "accept-receipt-subject-mismatch",
        "    if receipt != expected:\n",
        "    if False:  # mutant: accept receipt subject mismatch\n",
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
        sys.stderr.write("baseline failed before invocation-resolution mutations\n")
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
    print(f"all {len(MUTATIONS)} invocation-resolution mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
