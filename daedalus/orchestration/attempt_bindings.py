"""Canonical, non-executing bindings from Renovation WorkItems to Attempts.

This module prepares restart/replay identity for the Gate-1 ignition slice.  It
creates no worktree, event store, SQLite ledger, effect lease, evidence packet,
nomination, approval, or promotion.  The authoritative lifecycle remains the
existing kernel/event spine; these records only prove which exact canonical
``AttemptContract`` belongs to which exact typed ``WorkItemContract``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Mapping, Sequence

from daedalus.schemas import (
    AttemptContract,
    CanonicalContract,
    ContractProvenance,
    MissionContract,
    _identifier,
    _revision,
    _sha256,
)
from daedalus.spine.envelope import canonical_sha
from daedalus.twin import FourfoldSnapshot

from .work_items import RenovationPlan, WorkItemContract, verify_renovation_plan

_REPLAY_SCHEMA = "daedalus-renovation-replay-key/1"
_SEQUENCE_BY_KIND = {"symbol-rename": 0, "representation-sync": 1}


class RenovationAttemptBindingError(ValueError):
    """Malformed, stale, widened, or authority-substituted attempt binding."""


def renovation_replay_key(
    *,
    renovation_plan_sha256: str,
    work_item_sha256: str,
    attempt_sha256: str,
    sequence: int,
) -> str:
    """Return the deterministic idempotency key for one exact planned attempt."""

    plan_digest = _sha256(renovation_plan_sha256, "renovation_plan_sha256")
    item_digest = _sha256(work_item_sha256, "work_item_sha256")
    attempt_digest = _sha256(attempt_sha256, "attempt_sha256")
    if isinstance(sequence, bool) or sequence not in (0, 1):
        raise RenovationAttemptBindingError("sequence must be exactly 0 or 1")
    return canonical_sha(
        {
            "schema": _REPLAY_SCHEMA,
            "renovation_plan_sha256": plan_digest,
            "work_item_sha256": item_digest,
            "attempt_sha256": attempt_digest,
            "sequence": sequence,
        }
    )


@dataclass(frozen=True)
class RenovationAttemptBinding(CanonicalContract):
    """One exact WorkItem-to-Attempt identity and deterministic replay key."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.renovation-attempt-binding"

    work_item_id: str
    work_item_sha256: str
    sequence: int
    replay_key: str
    attempt: AttemptContract
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "work_item_id", _identifier(self.work_item_id, "work_item_id")
        )
        object.__setattr__(
            self,
            "work_item_sha256",
            _sha256(self.work_item_sha256, "work_item_sha256"),
        )
        if isinstance(self.sequence, bool) or self.sequence not in (0, 1):
            raise RenovationAttemptBindingError("sequence must be exactly 0 or 1")
        object.__setattr__(
            self, "replay_key", _sha256(self.replay_key, "replay_key")
        )
        if not isinstance(self.attempt, AttemptContract):
            raise RenovationAttemptBindingError(
                "attempt must be a canonical AttemptContract"
            )
        if self.attempt.task_id != self.work_item_id:
            raise RenovationAttemptBindingError(
                "attempt task_id must equal the bound work_item_id"
            )
        if self.attempt.task_sha256 != self.work_item_sha256:
            raise RenovationAttemptBindingError(
                "attempt task digest must equal the bound work-item digest"
            )
        if self.provenance.source_revision != self.attempt.base_revision:
            raise RenovationAttemptBindingError(
                "binding provenance must use the attempt base revision"
            )
        expected_inputs = tuple(
            sorted(
                {
                    self.work_item_sha256,
                    self.attempt.digest,
                    self.replay_key,
                }
            )
        )
        if tuple(self.provenance.input_digests) != expected_inputs:
            raise RenovationAttemptBindingError(
                "binding provenance must bind exactly work item, attempt, and replay key"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.CONTRACT_TYPE,
            "contract_version": self.CONTRACT_VERSION,
            "work_item_id": self.work_item_id,
            "work_item_sha256": self.work_item_sha256,
            "sequence": self.sequence,
            "replay_key": self.replay_key,
            "attempt": self.attempt.to_dict(),
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RenovationAttemptBinding":
        body = cls._contract_payload(payload)
        raw_attempt = body.get("attempt")
        raw_provenance = body.get("provenance")
        if not isinstance(raw_attempt, Mapping):
            raise RenovationAttemptBindingError("attempt must be an object")
        if not isinstance(raw_provenance, Mapping):
            raise RenovationAttemptBindingError("provenance must be an object")
        body["attempt"] = AttemptContract.from_dict(raw_attempt)
        body["provenance"] = ContractProvenance.from_dict(raw_provenance)
        return cls(**body)


@dataclass(frozen=True)
class RenovationAttemptPlan(CanonicalContract):
    """Exactly two canonical attempts bound to one exact RenovationPlan."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.renovation-attempt-plan"

    attempt_plan_id: str
    renovation_plan_id: str
    renovation_plan_sha256: str
    mission_id: str
    base_revision: str
    bindings: tuple[RenovationAttemptBinding, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("attempt_plan_id", "renovation_plan_id", "mission_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "renovation_plan_sha256",
            _sha256(self.renovation_plan_sha256, "renovation_plan_sha256"),
        )
        object.__setattr__(
            self, "base_revision", _revision(self.base_revision, "base_revision")
        )
        bindings = tuple(self.bindings)
        if len(bindings) != 2 or any(
            not isinstance(binding, RenovationAttemptBinding)
            for binding in bindings
        ):
            raise RenovationAttemptBindingError(
                "attempt plan must contain exactly two attempt bindings"
            )
        bindings = tuple(sorted(bindings, key=lambda binding: binding.sequence))
        if tuple(binding.sequence for binding in bindings) != (0, 1):
            raise RenovationAttemptBindingError(
                "attempt bindings must cover sequence 0 and 1 exactly"
            )
        if len({binding.work_item_id for binding in bindings}) != 2:
            raise RenovationAttemptBindingError("work-item bindings must be unique")
        if len({binding.attempt.attempt_id for binding in bindings}) != 2:
            raise RenovationAttemptBindingError("attempt identifiers must be unique")
        if len({binding.replay_key for binding in bindings}) != 2:
            raise RenovationAttemptBindingError("replay keys must be unique")
        object.__setattr__(self, "bindings", bindings)
        if any(
            binding.attempt.mission_id != self.mission_id for binding in bindings
        ):
            raise RenovationAttemptBindingError(
                "every attempt must bind the attempt-plan mission"
            )
        if any(
            binding.attempt.base_revision != self.base_revision
            for binding in bindings
        ):
            raise RenovationAttemptBindingError(
                "every attempt must bind the attempt-plan base revision"
            )
        if self.provenance.source_revision != self.base_revision:
            raise RenovationAttemptBindingError(
                "attempt-plan provenance must use the base revision"
            )
        expected_inputs = tuple(
            sorted(
                {
                    self.renovation_plan_sha256,
                    *(binding.digest for binding in bindings),
                }
            )
        )
        if tuple(self.provenance.input_digests) != expected_inputs:
            raise RenovationAttemptBindingError(
                "attempt-plan provenance must bind exactly plan and bindings"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.CONTRACT_TYPE,
            "contract_version": self.CONTRACT_VERSION,
            "attempt_plan_id": self.attempt_plan_id,
            "renovation_plan_id": self.renovation_plan_id,
            "renovation_plan_sha256": self.renovation_plan_sha256,
            "mission_id": self.mission_id,
            "base_revision": self.base_revision,
            "bindings": [binding.to_dict() for binding in self.bindings],
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RenovationAttemptPlan":
        body = cls._contract_payload(payload)
        raw_bindings = body.get("bindings")
        raw_provenance = body.get("provenance")
        if isinstance(raw_bindings, (str, bytes)) or not isinstance(
            raw_bindings, (list, tuple)
        ):
            raise RenovationAttemptBindingError("bindings must be an array")
        if not isinstance(raw_provenance, Mapping):
            raise RenovationAttemptBindingError("provenance must be an object")
        body["bindings"] = tuple(
            RenovationAttemptBinding.from_dict(binding)
            for binding in raw_bindings
        )
        body["provenance"] = ContractProvenance.from_dict(raw_provenance)
        return cls(**body)


def _canonical_rebuild_attempt(attempt: AttemptContract) -> AttemptContract:
    if not isinstance(attempt, AttemptContract):
        raise RenovationAttemptBindingError(
            "attempts must contain AttemptContract records"
        )
    rebuilt = AttemptContract.from_dict(attempt.to_dict())
    if rebuilt != attempt:
        raise RenovationAttemptBindingError(
            "attempt does not equal its canonical reconstruction"
        )
    return rebuilt


def verify_renovation_attempt_plan(
    attempt_plan: RenovationAttemptPlan,
    *,
    renovation_plan: RenovationPlan,
    mission: MissionContract,
    base_snapshot: FourfoldSnapshot,
    expected_runtime_manifest_sha256: str,
    expected_policy_decision_sha256: str,
) -> RenovationAttemptPlan:
    """Recompute every authority binding before an attempt plan is consumed."""

    runtime_digest = _sha256(
        expected_runtime_manifest_sha256, "expected_runtime_manifest_sha256"
    )
    policy_digest = _sha256(
        expected_policy_decision_sha256, "expected_policy_decision_sha256"
    )
    if not isinstance(attempt_plan, RenovationAttemptPlan):
        raise RenovationAttemptBindingError(
            "attempt_plan must be a RenovationAttemptPlan"
        )
    try:
        rebuilt_attempt_plan = RenovationAttemptPlan.from_dict(
            attempt_plan.to_dict()
        )
        verified_plan = verify_renovation_plan(
            renovation_plan,
            mission=mission,
            base_snapshot=base_snapshot,
        )
    except ValueError as exc:
        raise RenovationAttemptBindingError(
            f"renovation attempt input is not canonical: {exc}"
        ) from exc
    if rebuilt_attempt_plan != attempt_plan:
        raise RenovationAttemptBindingError(
            "attempt plan does not equal its canonical reconstruction"
        )

    mismatches: list[str] = []
    if attempt_plan.renovation_plan_id != verified_plan.plan_id:
        mismatches.append("renovation_plan_id")
    if attempt_plan.renovation_plan_sha256 != verified_plan.digest:
        mismatches.append("renovation_plan_sha256")
    if attempt_plan.mission_id != mission.mission_id:
        mismatches.append("mission_id")
    if attempt_plan.base_revision != base_snapshot.source_revision:
        mismatches.append("base_revision")

    bindings_by_item = {
        binding.work_item_id: binding for binding in attempt_plan.bindings
    }
    items_by_id = {item.work_item_id: item for item in verified_plan.work_items}
    if set(bindings_by_item) != set(items_by_id):
        mismatches.append("work_item_ids")
    else:
        for item_id, item in items_by_id.items():
            binding = bindings_by_item[item_id]
            attempt = _canonical_rebuild_attempt(binding.attempt)
            expected_sequence = _SEQUENCE_BY_KIND[item.kind]
            expected_replay = renovation_replay_key(
                renovation_plan_sha256=verified_plan.digest,
                work_item_sha256=item.digest,
                attempt_sha256=attempt.digest,
                sequence=expected_sequence,
            )
            if binding.work_item_sha256 != item.digest:
                mismatches.append(f"{item_id}:work_item_sha256")
            if binding.sequence != expected_sequence:
                mismatches.append(f"{item_id}:sequence")
            if binding.replay_key != expected_replay:
                mismatches.append(f"{item_id}:replay_key")
            if attempt.mission_id != mission.mission_id:
                mismatches.append(f"{item_id}:attempt_mission_id")
            if attempt.task_id != item.work_item_id:
                mismatches.append(f"{item_id}:attempt_task_id")
            if attempt.task_sha256 != item.digest:
                mismatches.append(f"{item_id}:attempt_task_sha256")
            if attempt.base_revision != verified_plan.base_revision:
                mismatches.append(f"{item_id}:attempt_base_revision")
            if tuple(attempt.writable_paths) != tuple(item.writable_paths):
                mismatches.append(f"{item_id}:writable_paths")
            if tuple(attempt.gate_names) != tuple(item.required_evidence):
                mismatches.append(f"{item_id}:gate_names")
            if attempt.read_only:
                mismatches.append(f"{item_id}:read_only")
            if attempt.runtime_manifest_sha256 != runtime_digest:
                mismatches.append(f"{item_id}:runtime_manifest_sha256")
            if attempt.policy_decision_sha256 != policy_digest:
                mismatches.append(f"{item_id}:policy_decision_sha256")
            if attempt.budget != mission.budget:
                mismatches.append(f"{item_id}:budget")
    if mismatches:
        raise RenovationAttemptBindingError(
            "renovation attempt binding mismatch: "
            + ", ".join(sorted(mismatches))
        )
    return attempt_plan


def assemble_renovation_attempt_plan(
    *,
    renovation_plan: RenovationPlan,
    mission: MissionContract,
    base_snapshot: FourfoldSnapshot,
    attempts: Sequence[AttemptContract],
    expected_runtime_manifest_sha256: str,
    expected_policy_decision_sha256: str,
    attempt_plan_id: str,
    created_at: str,
) -> RenovationAttemptPlan:
    """Assemble and immediately reverify the exact two attempt bindings."""

    verified_plan = verify_renovation_plan(
        renovation_plan,
        mission=mission,
        base_snapshot=base_snapshot,
    )
    if isinstance(attempts, (str, bytes)):
        raise RenovationAttemptBindingError("attempts must be a sequence")
    canonical_attempts = tuple(_canonical_rebuild_attempt(item) for item in attempts)
    by_task = {attempt.task_id: attempt for attempt in canonical_attempts}
    if len(canonical_attempts) != 2 or len(by_task) != 2:
        raise RenovationAttemptBindingError(
            "exactly two unique canonical attempts are required"
        )
    bindings: list[RenovationAttemptBinding] = []
    for item in verified_plan.work_items:
        attempt = by_task.get(item.work_item_id)
        if attempt is None:
            raise RenovationAttemptBindingError(
                f"missing attempt for work item {item.work_item_id!r}"
            )
        sequence = _SEQUENCE_BY_KIND[item.kind]
        replay_key = renovation_replay_key(
            renovation_plan_sha256=verified_plan.digest,
            work_item_sha256=item.digest,
            attempt_sha256=attempt.digest,
            sequence=sequence,
        )
        bindings.append(
            RenovationAttemptBinding(
                work_item_id=item.work_item_id,
                work_item_sha256=item.digest,
                sequence=sequence,
                replay_key=replay_key,
                attempt=attempt,
                provenance=ContractProvenance(
                    origin="daedalus.orchestration.attempt-binding",
                    source_revision=verified_plan.base_revision,
                    created_at=created_at,
                    input_digests=(item.digest, attempt.digest, replay_key),
                    trace_id=attempt.attempt_id,
                ),
            )
        )
    result = RenovationAttemptPlan(
        attempt_plan_id=attempt_plan_id,
        renovation_plan_id=verified_plan.plan_id,
        renovation_plan_sha256=verified_plan.digest,
        mission_id=mission.mission_id,
        base_revision=verified_plan.base_revision,
        bindings=tuple(bindings),
        provenance=ContractProvenance(
            origin="daedalus.orchestration.renovation-attempt-plan",
            source_revision=verified_plan.base_revision,
            created_at=created_at,
            input_digests=(
                verified_plan.digest,
                *(binding.digest for binding in bindings),
            ),
            trace_id=attempt_plan_id,
        ),
    )
    return verify_renovation_attempt_plan(
        result,
        renovation_plan=verified_plan,
        mission=mission,
        base_snapshot=base_snapshot,
        expected_runtime_manifest_sha256=expected_runtime_manifest_sha256,
        expected_policy_decision_sha256=expected_policy_decision_sha256,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RenovationAttemptBindingError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def parse_renovation_attempt_plan(
    payload: Mapping[str, Any],
) -> RenovationAttemptPlan:
    """Parse only the exact canonical attempt-plan wire representation."""

    if not isinstance(payload, Mapping):
        raise RenovationAttemptBindingError("attempt plan must be an object")
    value = RenovationAttemptPlan.from_dict(payload)
    if dict(payload) != value.to_dict():
        raise RenovationAttemptBindingError("attempt-plan wire is not canonical")
    return value


def load_renovation_attempt_plan(path: str | Path) -> RenovationAttemptPlan:
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(payload, Mapping):
        raise RenovationAttemptBindingError("attempt-plan JSON root must be an object")
    return parse_renovation_attempt_plan(payload)
