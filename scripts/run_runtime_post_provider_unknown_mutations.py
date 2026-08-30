#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Run bounded mutations over the post-provider unknown-outcome boundary."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BROKER_TARGET = ROOT / "daedalus/runtimes/broker.py"
RECOVERY_TARGET = ROOT / "daedalus/runtimes/recovery.py"
BEHAVIOR = "tests/runtimes/test_runtime_provider_broker.py"
DURABLE = "tests/runtimes/test_runtime_provider_post_invoke_unknown.py"
BROKER_REVIEW = "tests/runtimes/test_runtime_provider_post_invoke_unknown_review.py"
RECOVERY = "tests/runtimes/test_runtime_provider_recovery.py"
RECOVERY_REVIEW = "tests/runtimes/test_runtime_provider_recovery_review.py"
MUTATIONS = {
    "restore-failed-terminal": (
        BROKER_TARGET,
        """    except BaseException as exc:\n        raise RuntimeProviderReconciliationRequired(\n            entrypoint_id=spec.id,\n            runtime_id=spec.runtime_id,\n            start_receipt=start.receipt,\n            phase=\"output-evidence\",\n            cause_sha256=_exception_detail(\"output-evidence\", exc),\n        ) from exc\n""",
        """    except BaseException as exc:\n        _finish_or_raise_state(\n            authorization,\n            start.receipt,\n            outcome=\"failed\",\n            detail_sha256=_exception_detail(\"output-evidence\", exc),\n        )\n        raise\n""",
        BEHAVIOR,
    ),
    "reinvoke-exact-replay": (
        BROKER_TARGET,
        "if not start.execute:\n        return RuntimeInvocationResult(",
        "if False and not start.execute:\n        return RuntimeInvocationResult(",
        DURABLE,
    ),
    "retain-provider-value": (
        BROKER_TARGET,
        "self.cause_sha256 = cause_sha256",
        "self.cause_sha256 = cause_sha256\n        self.value = object()",
        BROKER_REVIEW,
    ),
    "expose-raw-cause-text": (
        BROKER_TARGET,
        '"authenticated reconciliation is required"',
        '"authenticated reconciliation is required: " + str(self.__cause__)',
        BROKER_REVIEW,
    ),
    "ignore-recovery-lease-binding": (
        RECOVERY_TARGET,
        """            start_receipt.lease_sha256,\n            authorization.capability.lease.digest,\n""",
        """            authorization.capability.lease.digest,\n            authorization.capability.lease.digest,\n""",
        RECOVERY,
    ),
    "ignore-recovery-idempotency-binding": (
        RECOVERY_TARGET,
        """            start_receipt.idempotency_key,\n            execution.idempotency_key,\n""",
        """            execution.idempotency_key,\n            execution.idempotency_key,\n""",
        RECOVERY,
    ),
    "accept-terminal-recovery": (
        RECOVERY_TARGET,
        "if not replay.pending_reconciliation:",
        "if False and not replay.pending_reconciliation:",
        RECOVERY,
    ),
    "ignore-recovery-source-revision": (
        RECOVERY_TARGET,
        """            authorization.capability.source_revision,\n            expected_source_revision,\n""",
        """            expected_source_revision,\n            expected_source_revision,\n""",
        RECOVERY,
    ),
}


def _run(*tests: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *tests],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
    )


def main() -> int:
    originals = {
        BROKER_TARGET: BROKER_TARGET.read_text(encoding="utf-8"),
        RECOVERY_TARGET: RECOVERY_TARGET.read_text(encoding="utf-8"),
    }
    try:
        baseline = _run(BEHAVIOR, DURABLE, BROKER_REVIEW, RECOVERY, RECOVERY_REVIEW)
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
        for name, (target, needle, replacement, selected) in MUTATIONS.items():
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
                completed = _run(selected)
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
    print(f"killed {len(MUTATIONS)} post-provider unknown-outcome mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
