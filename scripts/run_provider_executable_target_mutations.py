#!/usr/bin/env python3
"""Run bounded mutations over the provider executable-target contract."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "daedalus/runtimes/provider_executable_targets.py"
BEHAVIOR = "tests/runtimes/test_provider_executable_targets.py"
REVIEW = "tests/runtimes/test_provider_executable_targets_review.py"

MUTATIONS = {
    "accept-target-manifest-subclass": (
        "    if type(manifest) is not ProviderExecutableTargetManifest:\n",
        "    if not isinstance(manifest, ProviderExecutableTargetManifest):\n",
    ),
    "accept-stale-target-revision": (
        "    if manifest.source_revision != identity.source_revision:\n",
        "    if False and manifest.source_revision != identity.source_revision:\n",
    ),
    "accept-foreign-identity-registry": (
        "    if manifest.identity_registry_sha256 != identity.registry_sha256:\n",
        "    if False and manifest.identity_registry_sha256 != identity.registry_sha256:\n",
    ),
    "accept-descriptor-substitution": (
        "    if mismatches:\n        raise ProviderExecutableTargetBindingError(\n",
        "    if False and mismatches:\n        raise ProviderExecutableTargetBindingError(\n",
    ),
    "accept-external-python-target": (
        '    r"^daedalus(?:\\.[a-z][a-z0-9_]*)*:"\n',
        '    r"^(?:daedalus|os)(?:\\.[a-z][a-z0-9_]*)*:"\n',
    ),
    "claim-targets-structurally-verified": (
        '            "targets_structurally_verified": False,\n',
        '            "targets_structurally_verified": True,\n',
    ),
    "claim-provider-execution-authority": (
        '            "provider_execution_allowed": False,\n',
        '            "provider_execution_allowed": True,\n',
    ),
    "detach-identity-descriptor": (
        '''        "identity_descriptor_sha256": (
            descriptor.identity_descriptor_sha256,
            identity.descriptor_sha256,
        ),
''',
        "",
    ),
    "detach-adapter-artifact": (
        '''        "adapter_artifact_sha256": (
            descriptor.adapter_artifact_sha256,
            identity.adapter_artifact_sha256,
        ),
''',
        "",
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
    print(f"killed {len(MUTATIONS)} provider executable-target mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
