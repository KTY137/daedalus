#!/usr/bin/env python3
"""Run bounded mutations against collector replay attestation."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / (
    "daedalus/gates/repository_write_chain_collector_attestation.py"
)
TESTS = ("tests/gates/test_repository_write_chain_collector_attestation.py",)
MUTATIONS = {
    "accept-chain-that-differs-from-replay": (
        "    if replayed.to_dict() != retained_result.to_dict():\n",
        "    if False and replayed.to_dict() != retained_result.to_dict():\n",
    ),
    "accept-invalid-collector-signature": (
        "    if not hmac.compare_digest(\n",
        "    if False and not hmac.compare_digest(\n",
    ),
    "accept-expired-attestation": (
        "    if instant >= expires:\n",
        "    if False and instant >= expires:\n",
    ),
    "accept-foreign-retained-subject": (
        "    if subject_mismatches:\n",
        "    if False and subject_mismatches:\n",
    ),
    "accept-attestation-binding-substitution": (
        "    if mismatches:\n"
        "        raise RepositoryWriteChainCollectorBindingError(\n"
        "            \"collector attestation binding mismatch: \" + "
        "\", \".join(mismatches)\n"
        "        )\n",
        "    if False and mismatches:\n"
        "        raise RepositoryWriteChainCollectorBindingError(\n"
        "            \"collector attestation binding mismatch: \" + "
        "\", \".join(mismatches)\n"
        "        )\n",
    ),
}


def main() -> int:
    original = MODULE.read_text(encoding="utf-8")
    survivors: list[str] = []
    try:
        for name, (needle, replacement) in MUTATIONS.items():
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            MODULE.write_text(
                original.replace(needle, replacement),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *TESTS],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=90,
                env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            )
            if completed.returncode == 0:
                survivors.append(name)
            MODULE.write_text(original, encoding="utf-8")
    finally:
        MODULE.write_text(original, encoding="utf-8")
    if survivors:
        print(
            "surviving mutations: " + ", ".join(survivors),
            file=sys.stderr,
        )
        return 1
    print(f"killed {len(MUTATIONS)} collector-attestation mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
