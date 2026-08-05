"""Canonical, revision-bound fault-matrix manifests and run receipts.

This module defines the machine contract for Gate-0 fault evidence.  It does not
inject a fault, execute a provider, mutate a repository, grant an Effect Lease,
or close a Gate.  A later harness may emit scenario receipts, but only the
mechanical verifier in this module can convert an exact passing run into the
existing ``FaultMatrixEvidence`` projection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from daedalus.gates.evidence import FaultMatrixEvidence
from daedalus.schemas import _identifier, _revision, _sha256
from daedalus.spine.envelope import canonical_sha

_REVISION_40 = re.compile(r"^[0-9a-f]{40}$")
_OUTCOMES = frozenset(
    {
        "blocked_before_effect",
        "recoverable_restart",
        "reconcile_only",
        "terminal_failure",
        "terminal_success_replay",
    }
)
_RESTART_POLICIES = frozenset(
    {
        "manual_retry",
        "retry_same_execution",
        "reconcile_only",
        "replay_only",
        "no_retry",
    }
)


class FaultMatrixContractError(RuntimeError):
    """Base class for malformed or detached fault-matrix evidence."""


class FaultMatrixShapeError(FaultMatrixContractError):
    """A fault manifest or receipt has a malformed wire shape."""


class FaultMatrixBindingError(FaultMatrixContractError):
    """A run receipt is detached from its manifest or revision."""


def _exact_revision(value: Any, label: str) -> str:
    try:
        revision = _revision(value, label)
    except (TypeError, ValueError) as exc:
        raise FaultMatrixShapeError(f"{label} is malformed") from exc
    if _REVISION_40.fullmatch(revision) is None:
        raise FaultMatrixShapeError(f"{label} must be an exact 40-hex commit")
    return revision


def _exact_identifier(value: Any, label: str) -> str:
    try:
        return _identifier(value, label)
    except (TypeError, ValueError) as exc:
        raise FaultMatrixShapeError(f"{label} is malformed") from exc


def _exact_digest(value: Any, label: str) -> str:
    try:
        return _sha256(value, label)
    except (TypeError, ValueError) as exc:
        raise FaultMatrixShapeError(f"{label} is malformed") from exc


def _identifier_tuple(
    value: Any,
    label: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise FaultMatrixShapeError(f"{label} must be an exact tuple")
    result = tuple(
        _exact_identifier(item, f"{label}[{index}]")
        for index, item in enumerate(value)
    )
    if not allow_empty and not result:
        raise FaultMatrixShapeError(f"{label} must not be empty")
    if len(result) != len(set(result)):
        raise FaultMatrixShapeError(f"{label} must not contain duplicates")
    if result != tuple(sorted(result)):
        raise FaultMatrixShapeError(f"{label} must be sorted canonically")
    return result


def _mapping(payload: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise FaultMatrixShapeError(f"{label} must be an object")
    if not all(type(key) is str for key in payload):
        raise FaultMatrixShapeError(f"{label} keys must be exact strings")
    return payload


@dataclass(frozen=True)
class FaultScenarioSpec:
    """One exact injection point and its mechanically expected durable state."""

    scenario_id: str
    injection_point: str
    targeted_invariants: tuple[str, ...]
    expected_outcome: str
    expected_durable_markers: tuple[str, ...]
    forbidden_durable_markers: tuple[str, ...]
    restart_policy: str
    process_termination: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scenario_id",
            _exact_identifier(self.scenario_id, "scenario_id"),
        )
        object.__setattr__(
            self,
            "injection_point",
            _exact_identifier(self.injection_point, "injection_point"),
        )
        object.__setattr__(
            self,
            "targeted_invariants",
            _identifier_tuple(
                self.targeted_invariants,
                "targeted_invariants",
                allow_empty=False,
            ),
        )
        object.__setattr__(
            self,
            "expected_durable_markers",
            _identifier_tuple(
                self.expected_durable_markers,
                "expected_durable_markers",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "forbidden_durable_markers",
            _identifier_tuple(
                self.forbidden_durable_markers,
                "forbidden_durable_markers",
                allow_empty=True,
            ),
        )
        if type(self.expected_outcome) is not str or (
            self.expected_outcome not in _OUTCOMES
        ):
            raise FaultMatrixShapeError("expected_outcome is unknown")
        if type(self.restart_policy) is not str or (
            self.restart_policy not in _RESTART_POLICIES
        ):
            raise FaultMatrixShapeError("restart_policy is unknown")
        if type(self.process_termination) is not bool:
            raise FaultMatrixShapeError("process_termination must be exact bool")
        overlap = set(self.expected_durable_markers).intersection(
            self.forbidden_durable_markers
        )
        if overlap:
            raise FaultMatrixShapeError(
                "expected and forbidden durable markers must be disjoint"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "injection_point": self.injection_point,
            "targeted_invariants": list(self.targeted_invariants),
            "expected_outcome": self.expected_outcome,
            "expected_durable_markers": list(self.expected_durable_markers),
            "forbidden_durable_markers": list(self.forbidden_durable_markers),
            "restart_policy": self.restart_policy,
            "process_termination": self.process_termination,
            "automatic_reexecution_allowed": False,
            "primary_checkout_mutation_allowed": False,
            "llm_evidence_allowed": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FaultScenarioSpec":
        payload = _mapping(payload, "fault scenario")
        fields = {
            "scenario_id",
            "injection_point",
            "targeted_invariants",
            "expected_outcome",
            "expected_durable_markers",
            "forbidden_durable_markers",
            "restart_policy",
            "process_termination",
            "automatic_reexecution_allowed",
            "primary_checkout_mutation_allowed",
            "llm_evidence_allowed",
        }
        if set(payload) != fields:
            raise FaultMatrixShapeError("fault scenario fields are not exact")
        for field in (
            "automatic_reexecution_allowed",
            "primary_checkout_mutation_allowed",
            "llm_evidence_allowed",
        ):
            if payload[field] is not False:
                raise FaultMatrixShapeError(
                    f"fault scenario contains unsupported claim: {field}"
                )
        try:
            return cls(
                scenario_id=payload["scenario_id"],
                injection_point=payload["injection_point"],
                targeted_invariants=tuple(payload["targeted_invariants"]),
                expected_outcome=payload["expected_outcome"],
                expected_durable_markers=tuple(
                    payload["expected_durable_markers"]
                ),
                forbidden_durable_markers=tuple(
                    payload["forbidden_durable_markers"]
                ),
                restart_policy=payload["restart_policy"],
                process_termination=payload["process_termination"],
            )
        except FaultMatrixContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise FaultMatrixShapeError("fault scenario is malformed") from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class FaultMatrixManifest:
    """Revision-pinned, exact inventory of all required fault scenarios."""

    matrix_id: str
    gate: int
    source_revision: str
    subject_entrypoint_id: str
    scenarios: tuple[FaultScenarioSpec, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "matrix_id", _exact_identifier(self.matrix_id, "matrix_id"))
        if type(self.gate) is not int or self.gate != 0:
            raise FaultMatrixShapeError("fault matrix gate must be exact integer 0")
        object.__setattr__(
            self,
            "source_revision",
            _exact_revision(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "subject_entrypoint_id",
            _exact_identifier(self.subject_entrypoint_id, "subject_entrypoint_id"),
        )
        if type(self.scenarios) is not tuple or not self.scenarios:
            raise FaultMatrixShapeError("scenarios must be a non-empty exact tuple")
        if any(type(item) is not FaultScenarioSpec for item in self.scenarios):
            raise FaultMatrixShapeError("scenarios must contain exact FaultScenarioSpec")
        ids = tuple(item.scenario_id for item in self.scenarios)
        points = tuple(item.injection_point for item in self.scenarios)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise FaultMatrixShapeError("scenario ids must be unique and sorted")
        if len(points) != len(set(points)):
            raise FaultMatrixShapeError("injection points must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-fault-matrix-manifest/1",
            "matrix_id": self.matrix_id,
            "gate": self.gate,
            "source_revision": self.source_revision,
            "subject_entrypoint_id": self.subject_entrypoint_id,
            "scenarios": [item.to_dict() for item in self.scenarios],
            "scenario_count": len(self.scenarios),
            "inventory_complete_claimed": False,
            "faults_executed": False,
            "gate_transition_authorized": False,
            "closed": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FaultMatrixManifest":
        payload = _mapping(payload, "fault matrix manifest")
        fields = {
            "schema",
            "matrix_id",
            "gate",
            "source_revision",
            "subject_entrypoint_id",
            "scenarios",
            "scenario_count",
            "inventory_complete_claimed",
            "faults_executed",
            "gate_transition_authorized",
            "closed",
        }
        if set(payload) != fields:
            raise FaultMatrixShapeError("fault matrix manifest fields are not exact")
        if payload["schema"] != "daedalus-fault-matrix-manifest/1":
            raise FaultMatrixShapeError("fault matrix manifest schema is wrong")
        for field in (
            "inventory_complete_claimed",
            "faults_executed",
            "gate_transition_authorized",
            "closed",
        ):
            if payload[field] is not False:
                raise FaultMatrixShapeError(
                    f"fault matrix manifest contains unsupported claim: {field}"
                )
        scenarios_value = payload["scenarios"]
        if type(scenarios_value) is not list:
            raise FaultMatrixShapeError("manifest scenarios must be an exact list")
        scenarios = tuple(FaultScenarioSpec.from_dict(item) for item in scenarios_value)
        if type(payload["scenario_count"]) is not int or (
            payload["scenario_count"] != len(scenarios)
        ):
            raise FaultMatrixShapeError("scenario_count does not match scenarios")
        return cls(
            matrix_id=payload["matrix_id"],
            gate=payload["gate"],
            source_revision=payload["source_revision"],
            subject_entrypoint_id=payload["subject_entrypoint_id"],
            scenarios=scenarios,
        )

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class FaultScenarioReceipt:
    """One harness-produced observation, with no authority claims."""

    scenario_id: str
    scenario_spec_sha256: str
    source_revision: str
    harness_revision: str
    injection_fingerprint: str
    observed_outcome: str
    durable_markers: tuple[str, ...]
    primary_checkout_before_sha256: str
    primary_checkout_after_sha256: str
    run_artifact_sha256: str
    automatic_reexecution_performed: bool = False
    llm_evidence_used: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario_id", _exact_identifier(self.scenario_id, "scenario_id"))
        object.__setattr__(
            self,
            "scenario_spec_sha256",
            _exact_digest(self.scenario_spec_sha256, "scenario_spec_sha256"),
        )
        object.__setattr__(
            self,
            "source_revision",
            _exact_revision(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "harness_revision",
            _exact_revision(self.harness_revision, "harness_revision"),
        )
        object.__setattr__(
            self,
            "injection_fingerprint",
            _exact_digest(self.injection_fingerprint, "injection_fingerprint"),
        )
        if type(self.observed_outcome) is not str or (
            self.observed_outcome not in _OUTCOMES
        ):
            raise FaultMatrixShapeError("observed_outcome is unknown")
        object.__setattr__(
            self,
            "durable_markers",
            _identifier_tuple(self.durable_markers, "durable_markers", allow_empty=True),
        )
        for field in (
            "primary_checkout_before_sha256",
            "primary_checkout_after_sha256",
            "run_artifact_sha256",
        ):
            object.__setattr__(
                self,
                field,
                _exact_digest(getattr(self, field), field),
            )
        if self.automatic_reexecution_performed is not False:
            raise FaultMatrixShapeError("automatic re-execution is forbidden")
        if self.llm_evidence_used is not False:
            raise FaultMatrixShapeError("LLM output cannot be hard fault evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-fault-scenario-receipt/1",
            "scenario_id": self.scenario_id,
            "scenario_spec_sha256": self.scenario_spec_sha256,
            "source_revision": self.source_revision,
            "harness_revision": self.harness_revision,
            "injection_fingerprint": self.injection_fingerprint,
            "observed_outcome": self.observed_outcome,
            "durable_markers": list(self.durable_markers),
            "primary_checkout_before_sha256": self.primary_checkout_before_sha256,
            "primary_checkout_after_sha256": self.primary_checkout_after_sha256,
            "run_artifact_sha256": self.run_artifact_sha256,
            "automatic_reexecution_performed": False,
            "llm_evidence_used": False,
            "gate_transition_authorized": False,
            "closed": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FaultScenarioReceipt":
        payload = _mapping(payload, "fault scenario receipt")
        fields = {
            "schema",
            "scenario_id",
            "scenario_spec_sha256",
            "source_revision",
            "harness_revision",
            "injection_fingerprint",
            "observed_outcome",
            "durable_markers",
            "primary_checkout_before_sha256",
            "primary_checkout_after_sha256",
            "run_artifact_sha256",
            "automatic_reexecution_performed",
            "llm_evidence_used",
            "gate_transition_authorized",
            "closed",
        }
        if set(payload) != fields:
            raise FaultMatrixShapeError("fault scenario receipt fields are not exact")
        if payload["schema"] != "daedalus-fault-scenario-receipt/1":
            raise FaultMatrixShapeError("fault scenario receipt schema is wrong")
        for field in (
            "automatic_reexecution_performed",
            "llm_evidence_used",
            "gate_transition_authorized",
            "closed",
        ):
            if payload[field] is not False:
                raise FaultMatrixShapeError(
                    f"fault scenario receipt contains unsupported claim: {field}"
                )
        markers = payload["durable_markers"]
        if type(markers) is not list:
            raise FaultMatrixShapeError("durable_markers must be an exact list")
        return cls(
            scenario_id=payload["scenario_id"],
            scenario_spec_sha256=payload["scenario_spec_sha256"],
            source_revision=payload["source_revision"],
            harness_revision=payload["harness_revision"],
            injection_fingerprint=payload["injection_fingerprint"],
            observed_outcome=payload["observed_outcome"],
            durable_markers=tuple(markers),
            primary_checkout_before_sha256=payload[
                "primary_checkout_before_sha256"
            ],
            primary_checkout_after_sha256=payload[
                "primary_checkout_after_sha256"
            ],
            run_artifact_sha256=payload["run_artifact_sha256"],
        )

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class FaultMatrixVerificationReceipt:
    """Mechanical comparison of one exact manifest with one exact run inventory."""

    matrix_id: str
    manifest_sha256: str
    source_revision: str
    harness_revision: str
    scenario_receipt_sha256s: tuple[str, ...]
    status: str
    failed_scenario_ids: tuple[str, ...]
    missing_scenario_ids: tuple[str, ...]
    extra_scenario_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "matrix_id", _exact_identifier(self.matrix_id, "matrix_id"))
        object.__setattr__(
            self,
            "manifest_sha256",
            _exact_digest(self.manifest_sha256, "manifest_sha256"),
        )
        object.__setattr__(
            self,
            "source_revision",
            _exact_revision(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "harness_revision",
            _exact_revision(self.harness_revision, "harness_revision"),
        )
        if type(self.scenario_receipt_sha256s) is not tuple:
            raise FaultMatrixShapeError("scenario receipt digests must be exact tuple")
        digests = tuple(
            _exact_digest(item, f"scenario_receipt_sha256s[{index}]")
            for index, item in enumerate(self.scenario_receipt_sha256s)
        )
        if digests != tuple(sorted(digests)) or len(digests) != len(set(digests)):
            raise FaultMatrixShapeError("scenario receipt digests must be unique and sorted")
        object.__setattr__(self, "scenario_receipt_sha256s", digests)
        for field in (
            "failed_scenario_ids",
            "missing_scenario_ids",
            "extra_scenario_ids",
        ):
            object.__setattr__(
                self,
                field,
                _identifier_tuple(getattr(self, field), field, allow_empty=True),
            )
        if type(self.status) is not str or self.status not in {"passed", "failed"}:
            raise FaultMatrixShapeError("fault matrix status is unknown")
        should_pass = not (
            self.failed_scenario_ids
            or self.missing_scenario_ids
            or self.extra_scenario_ids
        )
        if (self.status == "passed") is not should_pass:
            raise FaultMatrixShapeError("fault matrix status disagrees with blockers")

    @property
    def failure_count(self) -> int:
        return (
            len(self.failed_scenario_ids)
            + len(self.missing_scenario_ids)
            + len(self.extra_scenario_ids)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-fault-matrix-verification/1",
            "matrix_id": self.matrix_id,
            "manifest_sha256": self.manifest_sha256,
            "source_revision": self.source_revision,
            "harness_revision": self.harness_revision,
            "scenario_receipt_sha256s": list(self.scenario_receipt_sha256s),
            "status": self.status,
            "failure_count": self.failure_count,
            "failed_scenario_ids": list(self.failed_scenario_ids),
            "missing_scenario_ids": list(self.missing_scenario_ids),
            "extra_scenario_ids": list(self.extra_scenario_ids),
            "inventory_complete": not (
                self.missing_scenario_ids or self.extra_scenario_ids
            ),
            "primary_checkout_unchanged": self.status == "passed",
            "automatic_reexecution_absent": self.status == "passed",
            "llm_evidence_absent": self.status == "passed",
            "gate_transition_authorized": False,
            "closed": False,
        }

    def to_fault_matrix_evidence(
        self,
        manifest: FaultMatrixManifest,
    ) -> FaultMatrixEvidence:
        if type(manifest) is not FaultMatrixManifest:
            raise FaultMatrixShapeError("manifest must be exact FaultMatrixManifest")
        if self.status != "passed":
            raise FaultMatrixBindingError(
                "failed fault matrix cannot become passing Gate evidence"
            )
        if (
            manifest.matrix_id != self.matrix_id
            or manifest.digest != self.manifest_sha256
            or manifest.source_revision != self.source_revision
        ):
            raise FaultMatrixBindingError(
                "fault matrix verification is detached from manifest"
            )
        return FaultMatrixEvidence(
            matrix_id=self.matrix_id,
            status="passed",
            scenario_ids=tuple(item.scenario_id for item in manifest.scenarios),
            failure_count=0,
            source_revision=self.source_revision,
        )

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def verify_fault_matrix_run(
    manifest: FaultMatrixManifest,
    receipts: Sequence[FaultScenarioReceipt],
    *,
    expected_source_revision: str,
    expected_harness_revision: str,
) -> FaultMatrixVerificationReceipt:
    """Compare one exact run inventory with one exact revision-pinned manifest."""

    if type(manifest) is not FaultMatrixManifest:
        raise FaultMatrixShapeError("manifest must be exact FaultMatrixManifest")
    source_revision = _exact_revision(
        expected_source_revision,
        "expected_source_revision",
    )
    harness_revision = _exact_revision(
        expected_harness_revision,
        "expected_harness_revision",
    )
    if manifest.source_revision != source_revision:
        raise FaultMatrixBindingError("manifest is pinned to a different source revision")
    if type(receipts) is not tuple:
        raise FaultMatrixShapeError("receipts must be an exact tuple")
    if any(type(item) is not FaultScenarioReceipt for item in receipts):
        raise FaultMatrixShapeError("receipts must contain exact FaultScenarioReceipt")

    receipt_by_id: dict[str, FaultScenarioReceipt] = {}
    duplicate_ids: set[str] = set()
    for receipt in receipts:
        if receipt.scenario_id in receipt_by_id:
            duplicate_ids.add(receipt.scenario_id)
        receipt_by_id[receipt.scenario_id] = receipt
    if duplicate_ids:
        raise FaultMatrixBindingError(
            "duplicate scenario receipts: " + ",".join(sorted(duplicate_ids))
        )

    spec_by_id = {item.scenario_id: item for item in manifest.scenarios}
    expected_ids = set(spec_by_id)
    observed_ids = set(receipt_by_id)
    missing = tuple(sorted(expected_ids - observed_ids))
    extra = tuple(sorted(observed_ids - expected_ids))
    failed: list[str] = []

    for scenario_id in sorted(expected_ids.intersection(observed_ids)):
        spec = spec_by_id[scenario_id]
        receipt = receipt_by_id[scenario_id]
        expected_markers = set(spec.expected_durable_markers)
        observed_markers = set(receipt.durable_markers)
        forbidden_markers = set(spec.forbidden_durable_markers)
        passed = (
            receipt.scenario_spec_sha256 == spec.digest
            and receipt.source_revision == source_revision
            and receipt.harness_revision == harness_revision
            and receipt.observed_outcome == spec.expected_outcome
            and expected_markers.issubset(observed_markers)
            and forbidden_markers.isdisjoint(observed_markers)
            and receipt.primary_checkout_before_sha256
            == receipt.primary_checkout_after_sha256
            and receipt.automatic_reexecution_performed is False
            and receipt.llm_evidence_used is False
        )
        if not passed:
            failed.append(scenario_id)

    blockers = tuple(sorted(failed)) + missing + extra
    status = "passed" if not blockers else "failed"
    return FaultMatrixVerificationReceipt(
        matrix_id=manifest.matrix_id,
        manifest_sha256=manifest.digest,
        source_revision=source_revision,
        harness_revision=harness_revision,
        scenario_receipt_sha256s=tuple(sorted(item.digest for item in receipts)),
        status=status,
        failed_scenario_ids=tuple(sorted(failed)),
        missing_scenario_ids=missing,
        extra_scenario_ids=extra,
    )


__all__ = [
    "FaultMatrixBindingError",
    "FaultMatrixContractError",
    "FaultMatrixManifest",
    "FaultMatrixShapeError",
    "FaultMatrixVerificationReceipt",
    "FaultScenarioReceipt",
    "FaultScenarioSpec",
    "verify_fault_matrix_run",
]
