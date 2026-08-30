#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Run bounded mutations against runtime-bound effect replay."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/kernel/runtime_effect_replay.py"
TEST_FILE = "tests/kernel/test_runtime_effect_replay_projection.py"
REVIEW_FILE = "tests/kernel/test_runtime_effect_replay_projection_review.py"
MUTATIONS = {
    "allow-untyped-authorization": (
        "if not isinstance(authorization, RuntimeBoundEffectAuthorization):",
        "if False and not isinstance(authorization, RuntimeBoundEffectAuthorization):",
        "test_projection_requires_exact_types",
    ),
    "erase-started-execution": (
        "if effect_snapshot is None:",
        "if effect_snapshot is not None:",
        "test_started_runtime_execution_projects_active_trust",
    ),
    "use-live-generation": (
        "authorization.capability.lease.kill_switch_generation\n            ),",
        "authorization.current_kill_switch_generation\n            ),",
        "test_started_runtime_execution_projects_active_trust",
    ),
    "bypass-runtime-authority-verification": (
        "trust_record = verify_runtime_bound_effect_lease(\n"
        "            authorization.capability,\n"
        "            request=authorization.request,\n"
        "            policy_decision=authorization.policy_decision,\n"
        "            lease_keyring=authorization.lease_keyring,\n"
        "            runtime_authority_keyring=authorization.runtime_authority_keyring,\n"
        "            runtime_trust_ledger=authorization.runtime_trust_ledger,\n"
        "            current_kill_switch_generation=(\n"
        "                authorization.capability.lease.kill_switch_generation\n"
        "            ),\n"
        "            now=start_instant,\n"
        "            registry=authorization.registry,\n"
        "        )",
        "trust_record = authorization.runtime_trust_ledger.records(\n"
        "            authorization.capability.runtime_id\n"
        "        )[0]",
        "test_wrong_runtime_authority_key_fails_closed",
    ),
    "ignore-trust-record-binding": (
        "if trust_record.record_sha256 != authorization.capability.runtime_trust_record_sha256:",
        "if False and trust_record.record_sha256 != authorization.capability.runtime_trust_record_sha256:",
        "test_verified_runtime_trust_digest_cannot_be_detached",
    ),
    "ignore-runtime-identity-binding": (
        "if trust_record.runtime_id != authorization.capability.runtime_id:",
        "if False and trust_record.runtime_id != authorization.capability.runtime_id:",
        "test_verified_runtime_identity_cannot_be_detached",
    ),
}


def _run(*tests: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *tests],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
        timeout=120,
        env={
            **os.environ,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        },
    )


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    try:
        baseline = _run(TEST_FILE, REVIEW_FILE)
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
        for name, (needle, replacement, test_name) in MUTATIONS.items():
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
                completed = _run(f"{TEST_FILE}::{test_name}")
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
    print(f"killed {len(MUTATIONS)} runtime-effect-replay mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
