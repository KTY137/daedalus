from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "daedalus" / "runtimes" / "provider" / "invocation_registry.py"
TESTS = (
    "tests/runtimes/test_provider_invocation_registry.py",
    "tests/runtimes/test_provider_invocation_registry_review.py",
)
MUTATIONS = (
    (
        "detach-implementation-identity-from-descriptor-digest",
        "    def to_dict(self) -> dict[str, str]:\n        return dataclasses.asdict(self)\n",
        "    def to_dict(self) -> dict[str, str]:\n        body = dataclasses.asdict(self)\n        body[\"implementation_id\"] = \"implementation.detached\"  # mutant\n        return body\n",
    ),
    (
        "accept-noncanonical-descriptor-order",
        "        if self.descriptors != tuple(\n            sorted(self.descriptors, key=lambda item: item.provider_id)\n        ):\n",
        "        if False:  # mutant: accept noncanonical ordering\n",
    ),
    (
        "accept-duplicate-provider-ids",
        "        if len(set(provider_ids)) != len(provider_ids):\n",
        "        if False:  # mutant: accept duplicate provider IDs\n",
    ),
    (
        "accept-stale-descriptor-revision",
        "        if stale:\n            raise ProviderInvocationRegistryShapeError(\n                \"registry descriptor source revision mismatch: \"\n                + \", \".join(stale)\n            )\n",
        "        if False:  # mutant: accept stale descriptor revision\n            raise ProviderInvocationRegistryShapeError(\n                \"registry descriptor source revision mismatch: \"\n                + \", \".join(stale)\n            )\n",
    ),
    (
        "ignore-artifact-digest-mismatch",
        "            \"adapter_artifact_sha256\": (\n                self.adapter_artifact_sha256,\n                subject.adapter_artifact_sha256,\n            ),\n",
        "            \"adapter_artifact_sha256\": (\n                subject.adapter_artifact_sha256,\n                subject.adapter_artifact_sha256,  # mutant\n            ),\n",
    ),
    (
        "ignore-config-digest-mismatch",
        "            \"adapter_config_sha256\": (\n                self.adapter_config_sha256,\n                subject.adapter_config_sha256,\n            ),\n",
        "            \"adapter_config_sha256\": (\n                subject.adapter_config_sha256,\n                subject.adapter_config_sha256,  # mutant\n            ),\n",
    ),
    (
        "accept-nonexact-resolve-subject",
        "    def resolve(\n        self,\n        subject: ProviderInvocationSubject,\n    ) -> ProviderAdapterDescriptor:\n        if type(subject) is not ProviderInvocationSubject:\n",
        "    def resolve(\n        self,\n        subject: ProviderInvocationSubject,\n    ) -> ProviderAdapterDescriptor:\n        if not isinstance(subject, ProviderInvocationSubject):  # mutant\n",
    ),
    (
        "accept-extra-manifest-fields",
        "        if not isinstance(payload, Mapping) or set(payload) != expected:\n            raise ProviderInvocationRegistryShapeError(\n                \"provider invocation registry fields are not exact\"\n            )\n",
        "        if not isinstance(payload, Mapping) or False:  # mutant\n            raise ProviderInvocationRegistryShapeError(\n                \"provider invocation registry fields are not exact\"\n            )\n",
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
        sys.stderr.write("baseline failed before invocation-registry mutations\n")
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
    print(f"all {len(MUTATIONS)} invocation-registry mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
