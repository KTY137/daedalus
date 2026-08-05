#!/usr/bin/env python3
"""Run bounded mutations over provider target structural verification."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "daedalus/runtimes/provider_target_verification.py"
CONTRACTS = ROOT / "daedalus/runtimes/provider_target_verification_contracts.py"
TESTS = (
    "tests/runtimes/test_provider_target_verification.py",
    "tests/runtimes/test_provider_target_verification_review.py",
)

MUTATIONS = {
    "accept-source-store-subclass": (
        VERIFIER,
        "    if type(source_store) is not SourceTreeStore:\n",
        "    if not isinstance(source_store, SourceTreeStore):\n",
    ),
    "accept-stale-source-revision": (
        VERIFIER,
        "    if source_manifest.source_revision != projection.source_revision:\n",
        "    if False and source_manifest.source_revision != projection.source_revision:\n",
    ),
    "accept-signed-source-digest-substitution": (
        VERIFIER,
        "    if entry.blob_sha256 != expected_source_sha256:\n",
        "    if False and entry.blob_sha256 != expected_source_sha256:\n",
    ),
    "trust-store-read-without-rehash": (
        VERIFIER,
        "    if hashlib.sha256(payload).hexdigest() != entry.blob_sha256:\n",
        "    if False and hashlib.sha256(payload).hexdigest() != entry.blob_sha256:\n",
    ),
    "accept-ambiguous-module": (
        VERIFIER,
        "    if len(matches) != 1:\n        raise ProviderTargetVerificationSourceError(\n            \"target module must resolve to exactly one source-tree file\"\n        )\n",
        "    if not matches:\n        raise ProviderTargetVerificationSourceError(\n            \"target module must resolve to exactly one source-tree file\"\n        )\n",
    ),
    "accept-ambiguous-definition": (
        VERIFIER,
        "        if len(matches) != 1:\n            raise ProviderTargetVerificationSourceError(\n                \"target qualified name is missing or structurally ambiguous\"\n            )\n",
        "        if not matches:\n            raise ProviderTargetVerificationSourceError(\n                \"target qualified name is missing or structurally ambiguous\"\n            )\n",
    ),
    "skip-receipt-signature": (
        VERIFIER,
        "    if not hmac.compare_digest(receipt.signature_sha256, expected_signature):\n",
        "    if False and not hmac.compare_digest(receipt.signature_sha256, expected_signature):\n",
    ),
    "detach-receipt-from-rebuilt-evidence": (
        VERIFIER,
        "    if receipt != expected:\n",
        "    if False and receipt != expected:\n",
    ),
    "claim-provider-execution-authority": (
        CONTRACTS,
        '            "provider_execution_allowed": False,\n',
        '            "provider_execution_allowed": True,\n',
    ),
    "drop-structural-verification-claim": (
        CONTRACTS,
        '            "targets_structurally_verified": True,\n',
        '            "targets_structurally_verified": False,\n',
    ),
}


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=360,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
    )


def main() -> int:
    originals = {
        VERIFIER: VERIFIER.read_text(encoding="utf-8"),
        CONTRACTS: CONTRACTS.read_text(encoding="utf-8"),
    }
    try:
        baseline = _run()
    except subprocess.TimeoutExpired:
        print("baseline timed out", file=sys.stderr)
        return 2
    if baseline.returncode != 0:
        print("baseline failed before mutations", file=sys.stderr)
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    survivors: list[str] = []
    timeouts: list[str] = []
    try:
        for name, (path, needle, replacement) in MUTATIONS.items():
            original = originals[path]
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            path.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
            try:
                completed = _run()
            except subprocess.TimeoutExpired:
                timeouts.append(name)
            else:
                if completed.returncode == 0:
                    survivors.append(name)
            finally:
                path.write_text(original, encoding="utf-8")
    finally:
        for path, original in originals.items():
            path.write_text(original, encoding="utf-8")

    if survivors or timeouts:
        if survivors:
            print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        if timeouts:
            print("timed-out mutations: " + ", ".join(timeouts), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} provider target verification mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
