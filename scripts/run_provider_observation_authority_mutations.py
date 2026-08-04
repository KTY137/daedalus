#!/usr/bin/env python3
"""Run bounded mutations over provider-observation authority binding."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BROKER = ROOT / "daedalus/runtimes/broker.py"
PROVIDER = ROOT / "daedalus/runtimes/provider_observation.py"
RECOVERY = ROOT / "daedalus/runtimes/recovery.py"
AUTHORITY_TEST = "tests/runtimes/test_provider_observation_authority.py"
DURABLE_TEST = "tests/runtimes/test_runtime_provider_post_invoke_unknown.py"
RECOVERY_TEST = "tests/runtimes/test_runtime_provider_recovery.py"
REVIEW_TEST = "tests/runtimes/test_provider_observation_authority_review.py"

MUTATIONS = {
    "skip-pre-invocation-authority-verification": (
        BROKER,
        """        else:\n            ledger.verify_authority(\n""",
        """        else:\n            if False:\n                ledger.verify_authority(\n""",
        DURABLE_TEST,
    ),
    "skip-durable-binding-before-invoke": (
        BROKER,
        """            ledger.bind_start(authority, start_receipt, bound_at=at)\n""",
        """            if False:\n                ledger.bind_start(authority, start_receipt, bound_at=at)\n""",
        DURABLE_TEST,
    ),
    "ignore-observation-keyring-digest": (
        PROVIDER,
        """        "observation_keyring_sha256": (\n            authority.observation_keyring_sha256,\n            observation_keyring_digest(observation_keyring),\n        ),\n""",
        """        "observation_keyring_sha256": (\n            authority.observation_keyring_sha256,\n            authority.observation_keyring_sha256,\n        ),\n""",
        AUTHORITY_TEST,
    ),
    "ignore-persisted-record-hmac": (
        PROVIDER,
        """        if not hmac.compare_digest(record.record_hmac_sha256, expected_hmac):\n""",
        """        if False and not hmac.compare_digest(record.record_hmac_sha256, expected_hmac):\n""",
        AUTHORITY_TEST,
    ),
    "accept-substituted-retained-authority": (
        PROVIDER,
        """        if record.authority != authority:\n""",
        """        if False and record.authority != authority:\n""",
        AUTHORITY_TEST,
    ),
    "accept-foreign-observation-provider": (
        RECOVERY,
        """    if observation.provider_id != record.authority.provider_id:\n""",
        """    if False and observation.provider_id != record.authority.provider_id:\n""",
        RECOVERY_TEST,
    ),
    "accept-foreign-observation-issuer": (
        RECOVERY,
        """    if observation.issuer_key_id not in record.authority.observation_issuer_key_ids:\n""",
        """    if False and observation.issuer_key_id not in record.authority.observation_issuer_key_ids:\n""",
        RECOVERY_TEST,
    ),
    "derive-provider-from-observation": (
        RECOVERY,
        "expected_provider_id=record.authority.provider_id,",
        "expected_provider_id=observation.provider_id,",
        REVIEW_TEST,
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
    originals = {
        BROKER: BROKER.read_text(encoding="utf-8"),
        PROVIDER: PROVIDER.read_text(encoding="utf-8"),
        RECOVERY: RECOVERY.read_text(encoding="utf-8"),
    }
    selected = (AUTHORITY_TEST, DURABLE_TEST, RECOVERY_TEST, REVIEW_TEST)
    try:
        baseline = _run(*selected)
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
        for name, (target, needle, replacement, test) in MUTATIONS.items():
            original = originals[target]
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            target.write_text(
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
                target.write_text(original, encoding="utf-8")
    finally:
        for target, original in originals.items():
            target.write_text(original, encoding="utf-8")

    if survivors or timeouts:
        if survivors:
            print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        if timeouts:
            print("timed-out mutations: " + ", ".join(timeouts), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} provider-observation authority mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
