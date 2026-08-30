#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Run bounded mutations over provider invocation identity projection."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/runtimes/provider_invocation_identity.py"
BEHAVIOR_TEST = "tests/runtimes/test_provider_invocation_identity.py"
REVIEW_TEST = "tests/runtimes/test_provider_invocation_identity_review.py"

MUTATIONS = {
    "derive-contract-from-authority": (
        "            invocation_contract_id=PROVIDER_INVOCATION_CONTRACT_ID,\n",
        "            invocation_contract_id=authority.invocation_contract_id,\n",
        BEHAVIOR_TEST,
    ),
    "derive-registry-digest-from-authority": (
        "            invocation_registry_sha256=registry.digest,\n",
        "            invocation_registry_sha256=authority.invocation_registry_sha256,\n",
        BEHAVIOR_TEST,
    ),
    "skip-exact-registry-resolution": (
        "        descriptor = registry.resolve(subject)\n",
        "        descriptor = registry.descriptor_for_provider(subject.provider_id)\n",
        BEHAVIOR_TEST,
    ),
    "allow-authority-subclass": (
        "    if type(authority) is not ProviderInvocationObservationAuthority:\n",
        "    if not isinstance(authority, ProviderInvocationObservationAuthority):\n",
        BEHAVIOR_TEST,
    ),
    "allow-registry-subclass": (
        "    if type(registry) is not ProviderInvocationRegistryManifest:\n",
        "    if not isinstance(registry, ProviderInvocationRegistryManifest):\n",
        BEHAVIOR_TEST,
    ),
    "allow-execution-subclass": (
        "    if type(execution) is not EffectExecutionRequest:\n",
        "    if not isinstance(execution, EffectExecutionRequest):\n",
        BEHAVIOR_TEST,
    ),
    "escalate-provider-execution": (
        '            "provider_execution_allowed": False,\n',
        '            "provider_execution_allowed": True,\n',
        REVIEW_TEST,
    ),
    "substitute-implementation-projection": (
        "        implementation_id=descriptor.implementation_id,\n",
        "        implementation_id=descriptor.adapter_id,\n",
        BEHAVIOR_TEST,
    ),
    "detach-authority-digest": (
        "        authority_sha256=authority.digest,\n",
        "        authority_sha256=authority.observation_authority.digest,\n",
        BEHAVIOR_TEST,
    ),
}


def _run(*tests: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *tests],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
    )


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    try:
        baseline = _run(BEHAVIOR_TEST, REVIEW_TEST)
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
        for name, (needle, replacement, test) in MUTATIONS.items():
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            TARGET.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
            try:
                completed = _run(test)
            except subprocess.TimeoutExpired:
                timeouts.append(name)
            else:
                if completed.returncode == 0:
                    survivors.append(name)
            finally:
                TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    if survivors or timeouts:
        if survivors:
            print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        if timeouts:
            print("timed-out mutations: " + ", ".join(timeouts), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} provider invocation identity mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
