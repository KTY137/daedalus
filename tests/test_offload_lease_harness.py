# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""One real, persisted ``python.offload`` Effect Lease per live call.

WHY THIS FILE EXISTS, AND WHAT IT REPLACED. Four test modules used to exercise
the live cascade by importing ``daedalus.offload._offload_impl`` and calling it
directly with ``live=True``. That shim was not a convenience -- it was the
measured defect: a write reachable from a leased caller AND from an un-leased
one cannot be attributed to the lease, so
``scripts/declare_write_surfaces.py`` refused to classify the ``worker.run``
surface at all, and ``python.offload`` authenticated while dominating zero
blocking write surfaces.

The planner no longer executes anything, so the shim cannot write any more
either. These tests therefore take the same door production takes: a lease is
issued, granted into a ledger, and consumed by the public :func:`offload`.
Every helper below is test material -- it mints its own issuer secret and its
own ledger under a temp directory, and it authorises nothing in the real tree.

There is deliberately no back door here. If a future test needs the live
cascade, it goes through :func:`live_offload`.
"""
from __future__ import annotations

import itertools
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import (EffectExecutionRequest, EffectLeaseLedger,
                                     LeasedEffectAuthorization,
                                     issue_effect_lease)
from daedalus.offload import offload as _public_offload
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, GuardDecision

REVISION = "a" * 40
SECRET = b"offload-lease-harness-test-secret-material-32b"
POLICY_SHA = "b" * 64

_SERIAL = itertools.count()
_STORE: Path | None = None


def _store() -> Path:
    """A process-local directory for the ledgers these leases are granted in.

    Outside any checkout under test, because a lease ledger must not be
    reachable by the thing the lease bounds -- the same reason
    ``daedalus.kernel.offload_lease`` keeps the production one beside the kill
    switch rather than inside the repository.
    """

    global _STORE
    if _STORE is None:
        _STORE = Path(tempfile.mkdtemp(prefix="offload-lease-harness-"))
    return _STORE


def issue(*, writable_paths: tuple[str, ...] = ("workspace",)):
    """``(authorization, execution, ledger)`` for one fresh live offload.

    Fresh per call on purpose: the ledger treats a repeated execution identity
    as a replay and refuses the second effect, so a shared request would make
    the second live call in a test silently inert.
    """

    suffix = f"{next(_SERIAL)}"
    now = datetime.now(timezone.utc)
    spec = REGISTRY_BY_ID["python.offload"]
    effects = tuple(sorted(effect.value for effect in spec.effects))
    scope = EffectScope(
        read_only=False,
        writable_paths=writable_paths,
        egress_endpoints=("https://provider.example.test",),
        tools=("python",),
        max_cost_microusd=1000,
        max_concurrency=1,
        timeout_s=60,
        kill_switch_ref="global-kill",
    )
    request = EffectLeaseRequest(
        request_id=f"harness-request-{suffix}",
        mission_id="harness-mission",
        attempt_id=f"harness-attempt-{suffix}",
        entrypoint_id=spec.id,
        requested_effects=effects,
        effect_scope=scope,
        idempotency_namespace=f"harness-{suffix}",
        kill_switch_generation=3,
        runtime_manifest_sha256=None,
        runtime_conformance_sha256=None,
        provenance=ContractProvenance(
            origin="tests.offload-lease-harness",
            source_revision=REVISION,
            created_at=now.isoformat(),
            trace_id="harness-mission",
        ),
    )
    policy = PolicyDecision(
        decision_id=f"harness-policy-{suffix}",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-02",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("bounded leased offload",),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin="tests.offload-lease-harness-policy",
            source_revision=REVISION,
            created_at=now.isoformat(),
            input_digests=(request.digest, POLICY_SHA),
            trace_id="harness-mission",
        ),
    )
    lease = issue_effect_lease(
        request,
        policy,
        lease_id=f"harness-lease-{suffix}",
        issuer_key_id="kernel-key",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=10),
        secret=SECRET,
    )
    ledger = EffectLeaseLedger(_store() / f"leases-{suffix}.sqlite3")
    ledger.grant(
        lease,
        request=request,
        policy_decision=policy,
        keyring={"kernel-key": SECRET},
        current_kill_switch_generation=3,
        granted_at=now,
    )
    authorization = LeasedEffectAuthorization(
        lease=lease,
        request=request,
        policy_decision=policy,
        ledger=ledger,
        keyring={"kernel-key": SECRET},
        guard_decisions=tuple(
            GuardDecision(
                contract,
                True,
                "artifact-locator:sha256:" + (str(index + 1) * 64)[:64],
            )
            for index, contract in enumerate(spec.guard_contracts)
        ),
        current_kill_switch_generation=3,
    )
    execution = EffectExecutionRequest(
        execution_id=f"harness-execution-{suffix}",
        idempotency_key=f"harness-idempotency-{suffix}",
        requested_effects=effects,
        writable_paths=writable_paths,
        egress_endpoints=("https://provider.example.test",),
        tools=("python",),
        max_cost_microusd=1000,
        kill_switch_ref="global-kill",
        kill_switch_generation=3,
    )
    return authorization, execution, ledger


def live_offload(*args, **kwargs) -> dict:
    """Call the public entrypoint live, behind a real lease.

    ``_attempt_workspace`` defaults to the target repo itself: the isolated-
    TaskAttempt refusal is a SEPARATE gate from the lease, tested on its own,
    and these callers are exercising routing/verification behaviour behind it.
    """

    repo_root = kwargs.get("repo_root")
    if repo_root is None and len(args) > 1:
        repo_root = args[1]
    kwargs.setdefault("_attempt_workspace", {"worktree": str(repo_root)})
    kwargs.setdefault("live", True)
    authorization, execution, _ledger = issue()
    kwargs.setdefault("effect_authorization", authorization)
    kwargs.setdefault("effect_execution", execution)
    result = _public_offload(*args, **kwargs)
    if kwargs["live"]:
        # Receipts ride on every LIVE leased result. Asserted, not merely
        # popped: without this a lease that silently stopped being consumed
        # would look exactly like a passing test. ``live=False`` is a planning
        # call and takes no lease at all -- that is the point of the split.
        assert "effect_start_receipt" in result, result
        result.pop("effect_start_receipt", None)
        result.pop("effect_terminal_receipt", None)
    return result
