"""Read-only restart/replay planning for the bounded Gate-1 Renovation slice.

The contracts in this module classify caller-supplied lifecycle observations for
the exactly two canonical Renovation Attempts.  They do not create a worktree,
persist lifecycle state, execute a runtime, issue an Effect Lease, construct
evidence, approve, merge, or promote.  The existing event spine remains the
lifecycle authority; consumers must supply its exact content-addressed receipt
identities and re-run verification before acting.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Mapping, Sequence

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    MissionContract,
    _identifier,
    _revision,
    _sha256,
)
from daedalus.twin import FourfoldSnapshot

from .attempt_bindings import (
    RenovationAttemptPlan,
    RenovationAttemptBindingError,
    verify_renovation_attempt_plan,
)
from .work_items import RenovationPlan

_OBSERVATION_STATES = frozenset(
    {"not-started", "started", "unknown", "succeeded", "failed", "cancelled"}
)
_REPLAY_ACTIONS = frozenset(
    {
        "execute",
        "blocked-dependency",
        "reconcile",
        "return-terminal",
        "restart-required",
    }
)
_TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})


class RenovationReplayError(ValueError):
    """Malformed, stale, contradictory, or authority-substituted replay input."""


def _optional_sha256(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, name)


@dataclass(frozen=True)
class AttemptLifecycleObservation(CanonicalContract):
    """One exact event-spine lifecycle observation for a planned Attempt."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.attempt-lifecycle-observation"

    attempt_id: str
    attempt_sha256: str
    replay_key: str
    sequence: int
    state: str
    start_receipt_sha256: str | None
    terminal_receipt_sha256: str | None
    source_revision: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_id", _identifier(self.attempt_id, "attempt_id"))
        object.__setattr__(
            self, "attempt_sha256", _sha256(self.attempt_sha256, "attempt_sha256")
        )
        object.__setattr__(self, "replay_key", _sha256(self.replay_key, "replay_key"))
        if isinstance(self.sequence, bool) or self.sequence not in (0, 1):
            raise RenovationReplayError("sequence must be exactly 0 or 1")
        state = _identifier(self.state, "state")
        if state not in _OBSERVATION_STATES:
            raise RenovationReplayError(f"unsupported lifecycle state {state!r}")
        object.__setattr__(self, "state", state)
        object.__setattr__(
            self,
            "start_receipt_sha256",
            _optional_sha256(self.start_receipt_sha256, "start_receipt_sha256"),
        )
        object.__setattr__(
            self,
            "terminal_receipt_sha256",
            _optional_sha256(self.terminal_receipt_sha256, "terminal_receipt_sha256"),
        )
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )

        if state == "not-started":
            if self.start_receipt_sha256 is not None or self.terminal_receipt_sha256 is not None:
                raise RenovationReplayError(
                    "not-started observation must not retain lifecycle receipts"
                )
        elif state in {"started", "unknown"}:
            if self.start_receipt_sha256 is None or self.terminal_receipt_sha256 is not None:
                raise RenovationReplayError(
                    f"{state} observation requires a start receipt and no terminal receipt"
                )
        elif state in _TERMINAL_STATES:
            if self.start_receipt_sha256 is None or self.terminal_receipt_sha256 is None:
                raise RenovationReplayError(
                    f"{state} observation requires start and terminal receipts"
                )

        if self.provenance.source_revision != self.source_revision:
            raise RenovationReplayError(
                "observation provenance must use the observed source revision"
            )
        expected_inputs = tuple(
            sorted(
                {
                    self.attempt_sha256,
                    self.replay_key,
                    *(
                        digest
                        for digest in (
                            self.start_receipt_sha256,
                            self.terminal_receipt_sha256,
                        )
                        if digest is not None
                    ),
                }
            )
        )
        if tuple(self.provenance.input_digests) != expected_inputs:
            raise RenovationReplayError(
                "observation provenance must bind exactly attempt, replay key, and receipts"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.CONTRACT_TYPE,
            "contract_version": self.CONTRACT_VERSION,
            "attempt_id": self.attempt_id,
            "attempt_sha256": self.attempt_sha256,
            "replay_key": self.replay_key,
            "sequence": self.sequence,
            "state": self.state,
            "start_receipt_sha256": self.start_receipt_sha256,
            "terminal_receipt_sha256": self.terminal_receipt_sha256,
            "source_revision": self.source_revision,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AttemptLifecycleObservation":
        body = cls._contract_payload(payload)
        raw_provenance = body.get("provenance")
        if not isinstance(raw_provenance, Mapping):
            raise RenovationReplayError("provenance must be an object")
        body["provenance"] = ContractProvenance.from_dict(raw_provenance)
        return cls(**body)


@dataclass(frozen=True)
class RenovationReplayDecision(CanonicalContract):
    """The only safe next action for one exact observed Attempt."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.renovation-replay-decision"

    work_item_id: str
    attempt_id: str
    attempt_sha256: str
    replay_key: str
    sequence: int
    observed_state: str
    action: str
    start_receipt_sha256: str | None
    terminal_receipt_sha256: str | None
    source_revision: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("work_item_id", "attempt_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self, "attempt_sha256", _sha256(self.attempt_sha256, "attempt_sha256")
        )
        object.__setattr__(self, "replay_key", _sha256(self.replay_key, "replay_key"))
        if isinstance(self.sequence, bool) or self.sequence not in (0, 1):
            raise RenovationReplayError("sequence must be exactly 0 or 1")
        observed_state = _identifier(self.observed_state, "observed_state")
        action = _identifier(self.action, "action")
        if observed_state not in _OBSERVATION_STATES:
            raise RenovationReplayError(
                f"unsupported observed state {observed_state!r}"
            )
        if action not in _REPLAY_ACTIONS:
            raise RenovationReplayError(f"unsupported replay action {action!r}")
        object.__setattr__(self, "observed_state", observed_state)
        object.__setattr__(self, "action", action)
        object.__setattr__(
            self,
            "start_receipt_sha256",
            _optional_sha256(self.start_receipt_sha256, "start_receipt_sha256"),
        )
        object.__setattr__(
            self,
            "terminal_receipt_sha256",
            _optional_sha256(self.terminal_receipt_sha256, "terminal_receipt_sha256"),
        )
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        if self.provenance.source_revision != self.source_revision:
            raise RenovationReplayError(
                "decision provenance must use the decision source revision"
            )

        allowed = {
            "not-started": {"execute", "blocked-dependency"},
            "started": {"reconcile"},
            "unknown": {"reconcile"},
            "succeeded": {"return-terminal"},
            "failed": {"restart-required"},
            "cancelled": {"restart-required"},
        }
        if action not in allowed[observed_state]:
            raise RenovationReplayError(
                f"action {action!r} is invalid for state {observed_state!r}"
            )
        if observed_state == "not-started":
            if self.start_receipt_sha256 is not None or self.terminal_receipt_sha256 is not None:
                raise RenovationReplayError(
                    "not-started decision must not retain lifecycle receipts"
                )
        elif observed_state in {"started", "unknown"}:
            if self.start_receipt_sha256 is None or self.terminal_receipt_sha256 is not None:
                raise RenovationReplayError(
                    "in-flight decision requires one start receipt and no terminal receipt"
                )
        else:
            if self.start_receipt_sha256 is None or self.terminal_receipt_sha256 is None:
                raise RenovationReplayError(
                    "terminal decision requires start and terminal receipts"
                )

        expected_inputs = tuple(
            sorted(
                {
                    self.attempt_sha256,
                    self.replay_key,
                    *(
                        digest
                        for digest in (
                            self.start_receipt_sha256,
                            self.terminal_receipt_sha256,
                        )
                        if digest is not None
                    ),
                }
            )
        )
        if tuple(self.provenance.input_digests) != expected_inputs:
            raise RenovationReplayError(
                "decision provenance must bind exactly attempt, replay key, and receipts"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.CONTRACT_TYPE,
            "contract_version": self.CONTRACT_VERSION,
            "work_item_id": self.work_item_id,
            "attempt_id": self.attempt_id,
            "attempt_sha256": self.attempt_sha256,
            "replay_key": self.replay_key,
            "sequence": self.sequence,
            "observed_state": self.observed_state,
            "action": self.action,
            "start_receipt_sha256": self.start_receipt_sha256,
            "terminal_receipt_sha256": self.terminal_receipt_sha256,
            "source_revision": self.source_revision,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RenovationReplayDecision":
        body = cls._contract_payload(payload)
        raw_provenance = body.get("provenance")
        if not isinstance(raw_provenance, Mapping):
            raise RenovationReplayError("provenance must be an object")
        body["provenance"] = ContractProvenance.from_dict(raw_provenance)
        return cls(**body)


@dataclass(frozen=True)
class RenovationReplayPlan(CanonicalContract):
    """Exactly two deterministic replay decisions for one Attempt plan."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.renovation-replay-plan"

    replay_plan_id: str
    attempt_plan_sha256: str
    mission_id: str
    base_revision: str
    decisions: tuple[RenovationReplayDecision, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("replay_plan_id", "mission_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "attempt_plan_sha256",
            _sha256(self.attempt_plan_sha256, "attempt_plan_sha256"),
        )
        object.__setattr__(
            self, "base_revision", _revision(self.base_revision, "base_revision")
        )
        decisions = tuple(self.decisions)
        if len(decisions) != 2 or any(
            not isinstance(item, RenovationReplayDecision) for item in decisions
        ):
            raise RenovationReplayError(
                "replay plan must contain exactly two replay decisions"
            )
        decisions = tuple(sorted(decisions, key=lambda item: item.sequence))
        if tuple(item.sequence for item in decisions) != (0, 1):
            raise RenovationReplayError(
                "replay decisions must cover sequence 0 and 1 exactly"
            )
        if len({item.attempt_id for item in decisions}) != 2:
            raise RenovationReplayError("replay decision attempts must be unique")
        if len({item.replay_key for item in decisions}) != 2:
            raise RenovationReplayError("replay decision keys must be unique")
        object.__setattr__(self, "decisions", decisions)
        if self.provenance.source_revision != self.base_revision:
            raise RenovationReplayError(
                "replay-plan provenance must use the base revision"
            )
        expected_inputs = tuple(
            sorted(
                {
                    self.attempt_plan_sha256,
                    *(decision.digest for decision in decisions),
                }
            )
        )
        if tuple(self.provenance.input_digests) != expected_inputs:
            raise RenovationReplayError(
                "replay-plan provenance must bind exactly attempt plan and decisions"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.CONTRACT_TYPE,
            "contract_version": self.CONTRACT_VERSION,
            "replay_plan_id": self.replay_plan_id,
            "attempt_plan_sha256": self.attempt_plan_sha256,
            "mission_id": self.mission_id,
            "base_revision": self.base_revision,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RenovationReplayPlan":
        body = cls._contract_payload(payload)
        raw_decisions = body.get("decisions")
        raw_provenance = body.get("provenance")
        if isinstance(raw_decisions, (str, bytes)) or not isinstance(
            raw_decisions, (list, tuple)
        ):
            raise RenovationReplayError("decisions must be an array")
        if not isinstance(raw_provenance, Mapping):
            raise RenovationReplayError("provenance must be an object")
        body["decisions"] = tuple(
            RenovationReplayDecision.from_dict(item) for item in raw_decisions
        )
        body["provenance"] = ContractProvenance.from_dict(raw_provenance)
        return cls(**body)


def _canonical_observations(
    observations: Sequence[AttemptLifecycleObservation],
) -> tuple[AttemptLifecycleObservation, AttemptLifecycleObservation]:
    if isinstance(observations, (str, bytes)):
        raise RenovationReplayError("observations must be a sequence")
    rebuilt: list[AttemptLifecycleObservation] = []
    for item in observations:
        if not isinstance(item, AttemptLifecycleObservation):
            raise RenovationReplayError(
                "observations must contain AttemptLifecycleObservation records"
            )
        canonical = AttemptLifecycleObservation.from_dict(item.to_dict())
        if canonical != item:
            raise RenovationReplayError(
                "observation does not equal its canonical reconstruction"
            )
        rebuilt.append(canonical)
    if len(rebuilt) != 2:
        raise RenovationReplayError("exactly two lifecycle observations are required")
    by_attempt = {item.attempt_id: item for item in rebuilt}
    if len(by_attempt) != 2:
        raise RenovationReplayError("lifecycle observation attempts must be unique")
    ordered = tuple(sorted(rebuilt, key=lambda item: item.sequence))
    if tuple(item.sequence for item in ordered) != (0, 1):
        raise RenovationReplayError(
            "lifecycle observations must cover sequence 0 and 1 exactly"
        )
    return ordered  # type: ignore[return-value]


def _derive_replay_plan(
    *,
    attempt_plan: RenovationAttemptPlan,
    observations: Sequence[AttemptLifecycleObservation],
    replay_plan_id: str,
    created_at: str,
) -> RenovationReplayPlan:
    canonical_observations = _canonical_observations(observations)
    observations_by_attempt = {
        item.attempt_id: item for item in canonical_observations
    }
    first_observation = canonical_observations[0]
    second_observation = canonical_observations[1]

    if second_observation.state != "not-started" and first_observation.state != "succeeded":
        raise RenovationReplayError(
            "dependent attempt cannot have lifecycle state before sequence 0 succeeds"
        )

    decisions: list[RenovationReplayDecision] = []
    for binding in attempt_plan.bindings:
        observation = observations_by_attempt.get(binding.attempt.attempt_id)
        if observation is None:
            raise RenovationReplayError(
                f"missing observation for attempt {binding.attempt.attempt_id!r}"
            )
        mismatches: list[str] = []
        if observation.attempt_sha256 != binding.attempt.digest:
            mismatches.append("attempt_sha256")
        if observation.replay_key != binding.replay_key:
            mismatches.append("replay_key")
        if observation.sequence != binding.sequence:
            mismatches.append("sequence")
        if observation.source_revision != attempt_plan.base_revision:
            mismatches.append("source_revision")
        if mismatches:
            raise RenovationReplayError(
                f"observation binding mismatch for {binding.attempt.attempt_id}: "
                + ", ".join(sorted(mismatches))
            )

        if observation.state == "not-started":
            dependency_satisfied = binding.sequence == 0 or first_observation.state == "succeeded"
            action = "execute" if dependency_satisfied else "blocked-dependency"
        elif observation.state in {"started", "unknown"}:
            action = "reconcile"
        elif observation.state == "succeeded":
            action = "return-terminal"
        else:
            action = "restart-required"

        decisions.append(
            RenovationReplayDecision(
                work_item_id=binding.work_item_id,
                attempt_id=binding.attempt.attempt_id,
                attempt_sha256=binding.attempt.digest,
                replay_key=binding.replay_key,
                sequence=binding.sequence,
                observed_state=observation.state,
                action=action,
                start_receipt_sha256=observation.start_receipt_sha256,
                terminal_receipt_sha256=observation.terminal_receipt_sha256,
                source_revision=attempt_plan.base_revision,
                provenance=ContractProvenance(
                    origin="daedalus.orchestration.replay-decision",
                    source_revision=attempt_plan.base_revision,
                    created_at=created_at,
                    input_digests=(
                        binding.attempt.digest,
                        binding.replay_key,
                        *(
                            digest
                            for digest in (
                                observation.start_receipt_sha256,
                                observation.terminal_receipt_sha256,
                            )
                            if digest is not None
                        ),
                    ),
                    trace_id=binding.attempt.attempt_id,
                ),
            )
        )

    return RenovationReplayPlan(
        replay_plan_id=replay_plan_id,
        attempt_plan_sha256=attempt_plan.digest,
        mission_id=attempt_plan.mission_id,
        base_revision=attempt_plan.base_revision,
        decisions=tuple(decisions),
        provenance=ContractProvenance(
            origin="daedalus.orchestration.renovation-replay-plan",
            source_revision=attempt_plan.base_revision,
            created_at=created_at,
            input_digests=(
                attempt_plan.digest,
                *(decision.digest for decision in decisions),
            ),
            trace_id=replay_plan_id,
        ),
    )


def assemble_renovation_replay_plan(
    *,
    attempt_plan: RenovationAttemptPlan,
    renovation_plan: RenovationPlan,
    mission: MissionContract,
    base_snapshot: FourfoldSnapshot,
    observations: Sequence[AttemptLifecycleObservation],
    expected_runtime_manifest_sha256: str,
    expected_policy_decision_sha256: str,
    replay_plan_id: str,
    created_at: str,
) -> RenovationReplayPlan:
    """Build replay decisions only after revalidating the complete parent authority."""

    verified_attempt_plan = verify_renovation_attempt_plan(
        attempt_plan,
        renovation_plan=renovation_plan,
        mission=mission,
        base_snapshot=base_snapshot,
        expected_runtime_manifest_sha256=expected_runtime_manifest_sha256,
        expected_policy_decision_sha256=expected_policy_decision_sha256,
    )
    result = _derive_replay_plan(
        attempt_plan=verified_attempt_plan,
        observations=observations,
        replay_plan_id=replay_plan_id,
        created_at=created_at,
    )
    return verify_renovation_replay_plan(
        result,
        attempt_plan=verified_attempt_plan,
        renovation_plan=renovation_plan,
        mission=mission,
        base_snapshot=base_snapshot,
        observations=observations,
        expected_runtime_manifest_sha256=expected_runtime_manifest_sha256,
        expected_policy_decision_sha256=expected_policy_decision_sha256,
    )


def verify_renovation_replay_plan(
    replay_plan: RenovationReplayPlan,
    *,
    attempt_plan: RenovationAttemptPlan,
    renovation_plan: RenovationPlan,
    mission: MissionContract,
    base_snapshot: FourfoldSnapshot,
    observations: Sequence[AttemptLifecycleObservation],
    expected_runtime_manifest_sha256: str,
    expected_policy_decision_sha256: str,
) -> RenovationReplayPlan:
    """Recompute the complete plan from caller-owned authority and observations."""

    if not isinstance(replay_plan, RenovationReplayPlan):
        raise RenovationReplayError(
            "replay_plan must be a RenovationReplayPlan"
        )
    try:
        rebuilt = RenovationReplayPlan.from_dict(replay_plan.to_dict())
        verified_attempt_plan = verify_renovation_attempt_plan(
            attempt_plan,
            renovation_plan=renovation_plan,
            mission=mission,
            base_snapshot=base_snapshot,
            expected_runtime_manifest_sha256=expected_runtime_manifest_sha256,
            expected_policy_decision_sha256=expected_policy_decision_sha256,
        )
        expected = _derive_replay_plan(
            attempt_plan=verified_attempt_plan,
            observations=observations,
            replay_plan_id=replay_plan.replay_plan_id,
            created_at=replay_plan.provenance.created_at,
        )
    except ValueError as exc:
        raise RenovationReplayError(
            f"renovation replay input is not canonical: {exc}"
        ) from exc
    if rebuilt != replay_plan:
        raise RenovationReplayError(
            "replay plan does not equal its canonical reconstruction"
        )
    if replay_plan != expected:
        raise RenovationReplayError(
            "replay plan does not equal the decision recomputed from current authority"
        )
    return replay_plan


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RenovationReplayError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def parse_attempt_lifecycle_observation(
    payload: Mapping[str, Any],
) -> AttemptLifecycleObservation:
    if not isinstance(payload, Mapping):
        raise RenovationReplayError("lifecycle observation must be an object")
    value = AttemptLifecycleObservation.from_dict(payload)
    if dict(payload) != value.to_dict():
        raise RenovationReplayError("lifecycle-observation wire is not canonical")
    return value


def parse_renovation_replay_plan(payload: Mapping[str, Any]) -> RenovationReplayPlan:
    if not isinstance(payload, Mapping):
        raise RenovationReplayError("replay plan must be an object")
    value = RenovationReplayPlan.from_dict(payload)
    if dict(payload) != value.to_dict():
        raise RenovationReplayError("replay-plan wire is not canonical")
    return value


def load_renovation_replay_plan(path: str | Path) -> RenovationReplayPlan:
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(payload, Mapping):
        raise RenovationReplayError("replay-plan JSON root must be an object")
    return parse_renovation_replay_plan(payload)
