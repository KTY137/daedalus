#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Run bounded mutations over the exact runtime-provider broker boundary."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BROKER = ROOT / "daedalus/runtimes/broker.py"
BROKER_TEST = "tests/runtimes/test_runtime_provider_broker.py"
BOUNDARY_TEST = "tests/runtimes/test_runtime_provider_exact_authority_boundary.py"
FORGED_TEST = "tests/runtimes/test_runtime_provider_post_invoke_unknown.py"
REVIEW_TEST = "tests/runtimes/test_provider_observation_authority_review.py"

MUTATIONS = {
    "accept-duck-typed-authorization": (
        "if type(authorization) is not RuntimeBoundEffectAuthorization:\n",
        "if False and type(authorization) is not RuntimeBoundEffectAuthorization:\n",
        BROKER_TEST,
    ),
    "accept-runtime-authorization-subclass": (
        "if type(authorization) is not RuntimeBoundEffectAuthorization:\n",
        "if not isinstance(authorization, RuntimeBoundEffectAuthorization):\n",
        BROKER_TEST,
    ),
    "accept-missing-or-subclassed-observation-authority": (
        "if type(authority) is not ProviderObservationAuthority:\n",
        "if False and type(authority) is not ProviderObservationAuthority:\n",
        BOUNDARY_TEST,
    ),
    "accept-missing-or-subclassed-binding-ledger": (
        "if type(ledger) is not ProviderObservationBindingLedger:\n",
        "if False and type(ledger) is not ProviderObservationBindingLedger:\n",
        BOUNDARY_TEST,
    ),
    "skip-all-pre-provider-observation-binding": (
        """    _prepare_observation_authority_after_start(\n        spec=spec,\n        authorization=authorization,\n        execution=execution,\n        start_receipt=start.receipt,\n        authority=authority,\n        ledger=binding_ledger,\n        replay=not start.execute,\n        at=_utc_now(),\n    )\n""",
        """    if False:\n        _prepare_observation_authority_after_start(\n            spec=spec,\n            authorization=authorization,\n            execution=execution,\n            start_receipt=start.receipt,\n            authority=authority,\n            ledger=binding_ledger,\n            replay=not start.execute,\n            at=_utc_now(),\n        )\n""",
        BROKER_TEST,
    ),
    "skip-fresh-binding-persistence": (
        "            ledger.bind_start(authority, start_receipt, bound_at=at)\n",
        "            if False:\n                ledger.bind_start(authority, start_receipt, bound_at=at)\n",
        BROKER_TEST,
    ),
    "skip-replay-retained-binding": (
        """        if replay:\n            ledger.require_bound(\n                authority,\n                start_receipt,\n                entrypoint_id=spec.id,\n                runtime_id=spec.runtime_id,\n                execution=execution,\n                lease_sha256=authorization.capability.lease.digest,\n                source_revision=authorization.capability.source_revision,\n            )\n""",
        """        if replay:\n            pass\n""",
        BOUNDARY_TEST,
    ),
    "skip-fresh-authority-verification": (
        """            ledger.verify_authority(\n                authority,\n                entrypoint_id=spec.id,\n                runtime_id=spec.runtime_id,\n                execution=execution,\n                lease_sha256=authorization.capability.lease.digest,\n                source_revision=authorization.capability.source_revision,\n                at=at,\n            )\n""",
        """            pass\n""",
        FORGED_TEST,
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
    original = BROKER.read_text(encoding="utf-8")
    selected = (BROKER_TEST, BOUNDARY_TEST, FORGED_TEST, REVIEW_TEST)
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
        for name, (needle, replacement, test) in MUTATIONS.items():
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            BROKER.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
            try:
                completed = _run(test, REVIEW_TEST)
            except subprocess.TimeoutExpired:
                timeouts.append(name)
            else:
                if completed.returncode == 0:
                    survivors.append(name)
            finally:
                BROKER.write_text(original, encoding="utf-8")
    finally:
        BROKER.write_text(original, encoding="utf-8")

    if survivors or timeouts:
        if survivors:
            print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        if timeouts:
            print("timed-out mutations: " + ", ".join(timeouts), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} exact-authority broker mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
