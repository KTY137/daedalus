# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effect_replay import (
    EffectReplayProjectionError,
    inspect_effect_execution,
)
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseLedger,
    issue_effect_lease,
)
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    Effect,
    EntrypointSpec,
    GuardDecision,
    Surface,
    Wiring,
)
from daedalus.spine.envelope import canonical_json, canonical_sha


REVISION = "a" * 40
POLICY_SHA = "b" * 64
SECRET = b"effect-replay-projection-secret-32-bytes-minimum"
NOW = datetime.now(timezone.utc).replace(microsecond=0)
ENTRYPOINT = "python.promote_candidates"
EFFECTS = tuple(
    sorted(
        (
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
            Effect.REPOSITORY_MUTATION.value,
        )
    )
)
GUARDS = (
    "containment.worktree",
    "promotion.owner_approval",
    "spine.intent_ledger",
)


def build_authorization(tmp_path):
    row = EntrypointSpec(
        id=ENTRYPOINT,
        surface=Surface.PYTHON,
        target="daedalus.kairos.gated_writes:promote_candidates",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.REPOSITORY_MUTATION,
        ),
        guard_contracts=GUARDS,
        wiring=Wiring.CENTRAL,
    )
    registry = {ENTRYPOINT: row}
    scope = EffectScope(
        read_only=False,
        writable_paths=("integration-worktrees", "state"),
        tools=("git",),
        max_cost_microusd=0,
        timeout_s=300,
        max_concurrency=1,
        kill_switch_ref="promotion-kill",
    )
    request = EffectLeaseRequest(
        request_id="effect-replay-request-1",
        mission_id="mission-1",
        attempt_id="promotion-1",
        entrypoint_id=ENTRYPOINT,
        requested_effects=EFFECTS,
        effect_scope=scope,
        idempotency_namespace="promotion-effects",
        kill_switch_generation=7,
        runtime_manifest_sha256=None,
        runtime_conformance_sha256=None,
        provenance=ContractProvenance(
            origin="tests.effect-replay-projection",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=("c" * 64,),
            trace_id="mission-1",
        ),
    )
    policy = PolicyDecision(
        decision_id="effect-replay-policy-1",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-04",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("bounded promotion effect",),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin="tests.effect-replay-policy",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(request.digest, POLICY_SHA),
            trace_id="mission-1",
        ),
    )
    lease = issue_effect_lease(
        request,
        policy,
        lease_id="effect-replay-lease-1",
        issuer_key_id="effect-replay-key-1",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        secret=SECRET,
        registry=registry,
    )
    generation = {"value": 7}
    authorization = NonRuntimeEffectAuthorization(
        lease=lease,
        request=request,
        policy_decision=policy,
        effect_ledger=EffectLeaseLedger(tmp_path / "effects.sqlite3"),
        lease_keyring={"effect-replay-key-1": SECRET},
        guard_decisions=(
            GuardDecision(
                "containment.worktree",
                True,
                "artifact:sha256:" + "d" * 64,
            ),
            GuardDecision(
                "promotion.owner_approval",
                True,
                "artifact:sha256:" + "e" * 64,
            ),
            GuardDecision(
                "spine.intent_ledger",
                True,
                "artifact:sha256:" + "f" * 64,
            ),
        ),
        kill_switch_generation_reader=lambda: generation["value"],
        registry=registry,
    )
    execution = EffectExecutionRequest(
        execution_id="promotion-1",
        idempotency_key="promotion-authorization-1",
        requested_effects=EFFECTS,
        writable_paths=("integration-worktrees/promotion-1", "state/spine.sqlite3"),
        tools=("git",),
        kill_switch_ref="promotion-kill",
        kill_switch_generation=7,
    )
    return authorization, execution, generation


def grant_and_start(tmp_path):
    authorization, execution, generation = build_authorization(tmp_path)
    authorization.grant()
    started = authorization.begin_effect(execution)
    assert started.execute is True
    return authorization, execution, generation, started.receipt


def test_persisted_lease_without_start_projects_none(tmp_path) -> None:
    authorization, execution, _generation = build_authorization(tmp_path)
    authorization.grant()
    assert inspect_effect_execution(authorization, execution) is None


def test_started_execution_projects_pending_without_using_live_generation(tmp_path) -> None:
    authorization, execution, generation, start = grant_and_start(tmp_path)
    generation["value"] = 99
    snapshot = inspect_effect_execution(authorization, execution)
    assert snapshot is not None
    assert snapshot.start_receipt == start
    assert snapshot.state == "STARTED"
    assert snapshot.terminal_receipt is None
    assert snapshot.pending_reconciliation is True


def test_terminal_execution_round_trips_exactly(tmp_path) -> None:
    authorization, execution, _generation, start = grant_and_start(tmp_path)
    terminal = authorization.finish_effect(
        start,
        outcome="completed",
        output_digests=("1" * 64, "2" * 64),
        detail_sha256="3" * 64,
    )
    snapshot = inspect_effect_execution(authorization, execution)
    assert snapshot is not None
    assert snapshot.state == "COMPLETED"
    assert snapshot.terminal_receipt == terminal
    assert snapshot.pending_reconciliation is False


def test_exact_terminal_remains_readable_after_later_revocation(tmp_path) -> None:
    authorization, execution, _generation, start = grant_and_start(tmp_path)
    terminal = authorization.finish_effect(start, outcome="failed")
    authorization.effect_ledger.revoke(
        authorization.lease.digest,
        reason="post-terminal administrative revocation",
    )
    snapshot = inspect_effect_execution(authorization, execution)
    assert snapshot is not None
    assert snapshot.terminal_receipt == terminal


def test_historical_projection_authenticates_original_lease_signature(tmp_path) -> None:
    authorization, execution, _generation, _start = grant_and_start(tmp_path)
    wrong_key = dataclasses.replace(
        authorization,
        lease_keyring={
            "effect-replay-key-1": b"wrong-effect-replay-secret-32-bytes-minimum"
        },
    )
    with pytest.raises(EffectReplayProjectionError, match="authenticate"):
        inspect_effect_execution(wrong_key, execution)


def test_cross_execution_identity_is_refused_not_treated_as_missing(tmp_path) -> None:
    authorization, execution, _generation, _start = grant_and_start(tmp_path)
    substituted = EffectExecutionRequest(
        execution_id=execution.execution_id,
        idempotency_key="another-idempotency-key",
        requested_effects=execution.requested_effects,
        writable_paths=execution.writable_paths,
        tools=execution.tools,
        kill_switch_ref=execution.kill_switch_ref,
        kill_switch_generation=execution.kill_switch_generation,
    )
    with pytest.raises(EffectReplayProjectionError, match="contradicts"):
        inspect_effect_execution(authorization, substituted)


def test_noncanonical_request_json_is_refused(tmp_path) -> None:
    authorization, execution, _generation, _start = grant_and_start(tmp_path)
    with sqlite3.connect(authorization.effect_ledger.path) as connection:
        connection.execute(
            "UPDATE effect_executions SET request_json=? WHERE execution_id=?",
            (json.dumps(execution.to_dict(), indent=2), execution.execution_id),
        )
    with pytest.raises(EffectReplayProjectionError, match="request_json"):
        inspect_effect_execution(authorization, execution)


def test_coherently_rehashed_start_subject_substitution_is_refused(tmp_path) -> None:
    authorization, execution, _generation, _start = grant_and_start(tmp_path)
    with sqlite3.connect(authorization.effect_ledger.path) as connection:
        raw = connection.execute(
            "SELECT start_receipt_json FROM effect_executions WHERE execution_id=?",
            (execution.execution_id,),
        ).fetchone()[0]
        parsed = json.loads(raw)
        parsed["execution_id"] = "promotion-2"
        payload = {
            key: value for key, value in parsed.items() if key != "receipt_sha256"
        }
        parsed["receipt_sha256"] = canonical_sha(payload)
        connection.execute(
            """
            UPDATE effect_executions
            SET start_receipt_json=?, start_receipt_sha256=?
            WHERE execution_id=?
            """,
            (canonical_json(parsed), parsed["receipt_sha256"], execution.execution_id),
        )
    with pytest.raises(EffectReplayProjectionError, match="execution_id"):
        inspect_effect_execution(authorization, execution)


def test_row_start_digest_must_bind_exact_start_receipt(tmp_path) -> None:
    authorization, execution, _generation, _start = grant_and_start(tmp_path)
    with sqlite3.connect(authorization.effect_ledger.path) as connection:
        connection.execute(
            "UPDATE effect_executions SET start_receipt_sha256=? WHERE execution_id=?",
            ("8" * 64, execution.execution_id),
        )
    with pytest.raises(EffectReplayProjectionError, match="start digest"):
        inspect_effect_execution(authorization, execution)


def test_started_row_cannot_hide_terminal_material(tmp_path) -> None:
    authorization, execution, _generation, _start = grant_and_start(tmp_path)
    with sqlite3.connect(authorization.effect_ledger.path) as connection:
        connection.execute(
            """
            UPDATE effect_executions
            SET finished_at=?, terminal_receipt_sha256=?, terminal_receipt_json=?
            WHERE execution_id=?
            """,
            (
                NOW.isoformat(timespec="microseconds"),
                "7" * 64,
                "{}",
                execution.execution_id,
            ),
        )
    with pytest.raises(EffectReplayProjectionError, match="terminal material"):
        inspect_effect_execution(authorization, execution)


def test_terminal_row_state_and_receipt_outcome_must_match(tmp_path) -> None:
    authorization, execution, _generation, start = grant_and_start(tmp_path)
    authorization.finish_effect(start, outcome="completed")
    with sqlite3.connect(authorization.effect_ledger.path) as connection:
        connection.execute(
            "UPDATE effect_executions SET state='FAILED' WHERE execution_id=?",
            (execution.execution_id,),
        )
    with pytest.raises(EffectReplayProjectionError, match="outcome"):
        inspect_effect_execution(authorization, execution)


def test_row_terminal_digest_must_bind_exact_terminal_receipt(tmp_path) -> None:
    authorization, execution, _generation, start = grant_and_start(tmp_path)
    authorization.finish_effect(start, outcome="failed")
    with sqlite3.connect(authorization.effect_ledger.path) as connection:
        connection.execute(
            "UPDATE effect_executions SET terminal_receipt_sha256=? WHERE execution_id=?",
            ("9" * 64, execution.execution_id),
        )
    with pytest.raises(EffectReplayProjectionError, match="terminal digest"):
        inspect_effect_execution(authorization, execution)


def test_projection_does_not_use_writer_connection(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorization, execution, _generation, _start = grant_and_start(tmp_path)

    def forbidden():
        raise AssertionError("read projection used EffectLeaseLedger._connect")

    monkeypatch.setattr(authorization.effect_ledger, "_connect", forbidden)
    snapshot = inspect_effect_execution(authorization, execution)
    assert snapshot is not None
    assert snapshot.pending_reconciliation is True
