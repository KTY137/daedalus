#!/usr/bin/env python3
"""Run bounded mutations against store resolution and chain admission."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLUTION = ROOT / "daedalus/gates/repository_write_chain_store_resolution.py"
ADMISSION = ROOT / "daedalus/gates/repository_write_chain_admission.py"
TESTS = (
    "tests/gates/test_repository_write_chain_store_resolution.py",
    "tests/gates/test_repository_write_chain_admission.py",
)
MUTATIONS = {
    "accept-store-inside-primary-checkout": (
        RESOLUTION,
        "    if _paths_overlap(root, checkout):\n",
        "    if False and _paths_overlap(root, checkout):\n",
    ),
    "accept-wrong-chain-media-type": (
        RESOLUTION,
        "    if manifest.get(\"media_type\") != CHAIN_RESULT_MEDIA_TYPE:\n",
        "    if False and manifest.get(\"media_type\") != CHAIN_RESULT_MEDIA_TYPE:\n",
    ),
    "accept-wrong-chain-metadata": (
        RESOLUTION,
        "    if manifest.get(\"metadata\") != CHAIN_RESULT_STORE_METADATA:\n",
        "    if False and manifest.get(\"metadata\") != CHAIN_RESULT_STORE_METADATA:\n",
    ),
    "accept-foreign-locator-provenance": (
        RESOLUTION,
        "    if provenance != expected_provenance:\n",
        "    if False and provenance != expected_provenance:\n",
    ),
    "accept-corrupt-resolved-bytes": (
        RESOLUTION,
        "    if actual_sha256 != expected_sha256:\n",
        "    if False and actual_sha256 != expected_sha256:\n",
    ),
    "accept-cross-wired-collector-attestation": (
        ADMISSION,
        "        if getattr(attestation, field_name) != expected\n",
        "        if False and getattr(attestation, field_name) != expected\n",
    ),
    "skip-collector-authentication": (
        ADMISSION,
        "        verify_repository_write_chain_collector_attestation(\n",
        "        (lambda *args, **kwargs: None)(\n",
    ),
}


def main() -> int:
    originals = {
        target: target.read_text(encoding="utf-8")
        for target, _, _ in MUTATIONS.values()
    }
    survivors: list[str] = []
    try:
        baseline = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *TESTS],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        )
        if baseline.returncode != 0:
            sys.stderr.write(baseline.stdout)
            sys.stderr.write(baseline.stderr)
            raise RuntimeError("focused chain-admission baseline is not green")

        for name, (target, needle, replacement) in MUTATIONS.items():
            original = originals[target]
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            target.write_text(
                original.replace(needle, replacement),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *TESTS],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            )
            if completed.returncode == 0:
                survivors.append(name)
            target.write_text(original, encoding="utf-8")
    finally:
        for target, original in originals.items():
            target.write_text(original, encoding="utf-8")
    if survivors:
        print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} repository-write chain admission mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
