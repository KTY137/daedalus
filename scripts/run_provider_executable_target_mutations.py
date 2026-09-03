#!/usr/bin/env python3
"""Run bounded mutations over the signed provider executable-target contract."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "daedalus/runtimes/provider/executable_targets.py"
BEHAVIOR = "tests/runtimes/test_provider_executable_targets.py"
REVIEW = "tests/runtimes/test_provider_executable_targets_review.py"

MUTATIONS = {
    "accept-target-authority-subclass": (
        "    if type(target_authority) is not ProviderExecutableTargetAuthority:\n",
        "    if not isinstance(target_authority, ProviderExecutableTargetAuthority):\n",
    ),
    "accept-target-manifest-subclass": (
        "    if type(target_authority) is not ProviderExecutableTargetAuthority:\n        raise ProviderExecutableTargetBindingError(\n            \"target_authority must be exact ProviderExecutableTargetAuthority\"\n        )\n    if type(manifest) is not ProviderExecutableTargetManifest:\n",
        "    if type(target_authority) is not ProviderExecutableTargetAuthority:\n        raise ProviderExecutableTargetBindingError(\n            \"target_authority must be exact ProviderExecutableTargetAuthority\"\n        )\n    if not isinstance(manifest, ProviderExecutableTargetManifest):\n",
    ),
    "skip-target-authority-signature": (
        "    if not hmac.compare_digest(target_authority.signature_sha256, signature):\n",
        "    if False and not hmac.compare_digest(target_authority.signature_sha256, signature):\n",
    ),
    "accept-unsigned-target-manifest": (
        "        \"target_manifest_sha256\": (\n            target_authority.target_manifest_sha256,\n            manifest.digest,\n        ),\n",
        "",
    ),
    "accept-foreign-target-contract": (
        "        \"target_contract_id\": (\n            target_authority.target_contract_id,\n            contract,\n        ),\n",
        "",
    ),
    "detach-target-descriptor": (
        "        \"target_descriptor_sha256\": (\n            target_authority.target_descriptor_sha256,\n            descriptor.digest,\n        ),\n",
        "",
    ),
    "detach-adapter-artifact": (
        "    comparisons = {\n        \"provider_id\": (descriptor.provider_id, identity.provider_id),\n        \"adapter_id\": (descriptor.adapter_id, identity.adapter_id),\n        \"implementation_id\": (\n            descriptor.implementation_id,\n            identity.implementation_id,\n        ),\n        \"entrypoint_id\": (descriptor.entrypoint_id, identity.entrypoint_id),\n        \"runtime_id\": (descriptor.runtime_id, identity.runtime_id),\n        \"source_revision\": (\n            descriptor.source_revision,\n            identity.source_revision,\n        ),\n        \"identity_descriptor_sha256\": (\n            descriptor.identity_descriptor_sha256,\n            identity.descriptor_sha256,\n        ),\n        \"adapter_artifact_sha256\": (\n            descriptor.adapter_artifact_sha256,\n            identity.adapter_artifact_sha256,\n        ),\n",
        "    comparisons = {\n        \"provider_id\": (descriptor.provider_id, identity.provider_id),\n        \"adapter_id\": (descriptor.adapter_id, identity.adapter_id),\n        \"implementation_id\": (\n            descriptor.implementation_id,\n            identity.implementation_id,\n        ),\n        \"entrypoint_id\": (descriptor.entrypoint_id, identity.entrypoint_id),\n        \"runtime_id\": (descriptor.runtime_id, identity.runtime_id),\n        \"source_revision\": (\n            descriptor.source_revision,\n            identity.source_revision,\n        ),\n        \"identity_descriptor_sha256\": (\n            descriptor.identity_descriptor_sha256,\n            identity.descriptor_sha256,\n        ),\n",
    ),
    "accept-external-python-target": (
        "    r\"^daedalus(?:\\\\.[a-z][a-z0-9_]*)*:\"\n",
        "    r\"^(?:daedalus|os)(?:\\\\.[a-z][a-z0-9_]*)*:\"\n",
    ),
    "claim-targets-structurally-verified": (
        "            \"targets_structurally_verified\": False,\n",
        "            \"targets_structurally_verified\": True,\n",
    ),
    "claim-provider-execution-authority": (
        "            \"provider_execution_allowed\": False,\n",
        "            \"provider_execution_allowed\": True,\n",
    ),
}


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", BEHAVIOR, REVIEW],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
    )


def main() -> int:
    original = MODULE.read_text(encoding="utf-8")
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
        for name, (needle, replacement) in MUTATIONS.items():
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            MODULE.write_text(
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
                MODULE.write_text(original, encoding="utf-8")
    finally:
        MODULE.write_text(original, encoding="utf-8")

    if survivors or timeouts:
        if survivors:
            print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        if timeouts:
            print("timed-out mutations: " + ", ".join(timeouts), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} signed provider target mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
