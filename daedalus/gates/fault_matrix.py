"""Revision-bound canonical contracts for Gate-0 fault evidence.

The contracts in this module are deliberately non-executing.  They inventory
fault scenarios and mechanically compare harness receipts, but they do not
inject faults, execute providers, mutate repositories, grant Effect Leases,
promote candidates, or close a Gate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from daedalus.gates.evidence import FaultMatrixEvidence
from daedalus.schemas import _identifier, _revision, _sha256
from daedalus.spine.envelope import canonical_sha

FINGERPRINT_ALGORITHM = "daedalus-fault-injection-fingerprint/1"
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
    """A manifest or receipt has a malformed or non-exact shape."""


class FaultMatrixBindingError(FaultMatrixContractError):
    """A receipt or projection is detached from its exact run subjects."""


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


def fault_injection_fingerprint(
    source_revision: str,
    scenario_id: str,
    injection_point: str,
) -> str:
    """Return the exact fingerprint for one revision-bound injection point."""

    return canonical_sha(
        {
            "schema": FINGERPRINT_ALGORITHM,
            "source_revision": _exact_revision(
                source_revision,
                "source_revision",
            ),
            "scenario_id": _exact_identifier(scenario_id, "scenario_id"),
            "injection_point": _exact_identifier(
                injection_point,
                "injection_point",
            ),
        }
    )


@dataclass(frozen=True)
class FaultScenarioSpec:
    """One exact injection point and its expected durable observation."""

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
        if set(self.expected_durable_markers).intersection(
            self.forbidden_durable_markers
        ):
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
    """Revision-pinned exact inventory of required fault scenarios."""

    matrix_id: str
    gate: int
    source_revision: str
    subject_entrypoint_id: str
    scenarios: tuple[FaultScenarioSpec, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "matrix_id",
            _exact_identifier(self.matrix_id, "matrix_id"),
        )
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
            _exact_identifier(
                self.subject_entrypoint_id,
                "subject_entrypoint_id",
            ),
        )
        if type(self.scenarios) is not tuple or not self.scenarios:
            raise FaultMatrixShapeError("scenarios must be a non-empty exact tuple")
        if any(type(item) is not FaultScenarioSpec for item in self.scenarios):
            raise FaultMatrixShapeError(
                "scenarios must contain exact FaultScenarioSpec"
            )
        ids = tuple(item.scenario_id for item in self.scenarios)
        points = tuple(item.injection_point for item in self.scenarios)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise FaultMatrixShapeError("scenario ids must be unique and sorted")
        if len(points) != len(set(points)):
            raise FaultMatrixShapeError("injection points must be unique")
        fingerprints = tuple(
            fault_injection_fingerprint(
                self.source_revision,
                item.scenario_id,
                item.injection_point,
            )
            for item in self.scenarios
        )
        if len(fingerprints) != len(set(fingerprints)):
            raise FaultMatrixShapeError("injection fingerprints must be unique")

    def injection_fingerprint(self, spec: FaultScenarioSpec) -> str:
        if type(spec) is not FaultScenarioSpec or spec not in self.scenarios:
            raise FaultMatrixBindingError(
                "scenario is not an exact member of this manifest"
            )
        return fault_injection_fingerprint(
            self.source_revision,
            spec.scenario_id,
            spec.injection_point,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-fault-matrix-manifest/1",
            "matrix_id": self.matrix_id,
            "gate": self.gate,
            "source_revision": self.source_revision,
            "subject_entrypoint_id": self.subject_entrypoint_id,
            "injection_fingerprint_algorithm": FINGERPRINT_ALGORITHM,
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
            "injection_fingerprint_algorithm",
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
        if payload["injection_fingerprint_algorithm"] != FINGERPRINT_ALGORITHM:
            raise FaultMatrixShapeError(
                "fault matrix fingerprint algorithm is unsupported"
            )
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
        scenarios = tuple(
            FaultScenarioSpec.from_dict(item) for item in scenarios_value
        )
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
    """One exact harness observation with no execution or Gate authority."""

    scenario_id: str
    scenario_spec_sha256: str
    source_revision: str
    harness_revision: str
    harness_runtime_sha256: str
    toolchain_manifest_sha256: str
    injection_fingerprint_sha256: str
    observed_outcome: str
    observed_restart_policy: str
    process_termination_observed: bool
    durable_markers: tuple[str, ...]
    primary_checkout_before_sha256: str
    primary_checkout_after_sha256: str
    run_artifact_sha256: str
    automatic_reexecution_performed: bool = False
    llm_evidence_used: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scenario_id",
            _exact_identifier(self.scenario_id, "scenario_id"),
        )
        for field in (
            "scenario_spec_sha256",
            "harness_runtime_sha256",
            "toolchain_manifest_sha256",
            "injection_fingerprint_sha256",
            "primary_checkout_before_sha256",
            "primary_checkout_after_sha256",
            "run_artifact_sha256",
        ):
            object.__setattr__(
                self,
                field,
                _exact_digest(getattr(self, field), field),
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
        if type(self.observed_outcome) is not str or (
            self.observed_outcome not in _OUTCOMES
        ):
            raise FaultMatrixShapeError("observed_outcome is unknown")
        if type(self.observed_restart_policy) is not str or (
            self.observed_restart_policy not in _RESTART_POLICIES
        ):
            raise FaultMatrixShapeError("observed_restart_policy is unknown")
        if type(self.process_termination_observed) is not bool:
            raise FaultMatrixShapeError(
                "process_termination_observed must be exact bool"
            )
        object.__setattr__(
            self,
            "durable_markers",
            _identifier_tuple(
                self.durable_markers,
                "durable_markers",
                allow_empty=True,
            ),
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
            "harness_runtime_sha256": self.harness_runtime_sha256,
            "toolchain_manifest_sha256": self.toolchain_manifest_sha256,
            "injection_fingerprint_sha256": (
                self.injection_fingerprint_sha256
            ),
            "observed_outcome": self.observed_outcome,
            "observed_restart_policy": self.observed_restart_policy,
            "process_termination_observed": self.process_termination_observed,
            "durable_markers": list(self.durable_markers),
            "primary_checkout_before_sha256": (
                self.primary_checkout_before_sha256
            ),
            "primary_checkout_after_sha256": (
                self.primary_checkout_after_sha256
            ),
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
            "harness_runtime_sha256",
            "toolchain_manifest_sha256",
            "injection_fingerprint_sha256",
            "observed_outcome",
            "observed_restart_policy",
            "process_termination_observed",
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
            harness_runtime_sha256=payload["harness_runtime_sha256"],
            toolchain_manifest_sha256=payload["toolchain_manifest_sha256"],
            injection_fingerprint_sha256=payload[
                "injection_fingerprint_sha256"
            ],
            observed_outcome=payload["observed_outcome"],
            observed_restart_policy=payload["observed_restart_policy"],
            process_termination_observed=payload[
                "process_termination_observed"
            ],
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
    """Mechanical comparison of one exact manifest and run inventory."""

    matrix_id: str
    manifest_sha256: str
    source_revision: str
    harness_revision: str
    harness_runtime_sha256: str
    toolchain_manifest_sha256: str
    scenario_receipt_sha256s: tuple[str, ...]
    status: str
    failed_scenario_ids: tuple[str, ...]
    missing_scenario_ids: tuple[str, ...]
    extra_scenario_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "matrix_id",
            _exact_identifier(self.matrix_id, "matrix_id"),
        )
        for field in (
            "manifest_sha256",
            "harness_runtime_sha256",
            "toolchain_manifest_sha256",
        ):
            object.__setattr__(
                self,
                field,
                _exact_digest(getattr(self, field), field),
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
            raise FaultMatrixShapeError(
                "scenario receipt digests must be exact tuple"
            )
        digests = tuple(
            _exact_digest(item, f"scenario_receipt_sha256s[{index}]")
            for index, item in enumerate(self.scenario_receipt_sha256s)
        )
        if digests != tuple(sorted(digests)) or len(digests) != len(set(digests)):
            raise FaultMatrixShapeError(
                "scenario receipt digests must be unique and sorted"
            )
        object.__setattr__(self, "scenario_receipt_sha256s", digests)
        for field in (
            "failed_scenario_ids",
            "missing_scenario_ids",
            "extra_scenario_ids",
        ):
            object.__setattr__(
                self,
                field,
                _identifier_tuple(
                    getattr(self, field),
                    field,
                    allow_empty=True,
                ),
            )
        if type(self.status) is not str or self.status not in {"passed", "failed"}:
            raise FaultMatrixShapeError("fault matrix status is unknown")
        should_pass = not (
            self.failed_scenario_ids
            or self.missing_scenario_ids
            or self.extra_scenario_ids
        )
        if (self.status == "passed") is not should_pass:
            raise FaultMatrixShapeError(
                "fault matrix status disagrees with blockers"
            )

    @property
    def failure_count(self) -> int:
        return (
            len(self.failed_scenario_ids)
            + len(self.missing_scenario_ids)
            + len(self.extra_scenario_ids)
        )

    def to_dict(self) -> dict[str, Any]:
        passed = self.status == "passed"
        return {
            "schema": "daedalus-fault-matrix-verification/1",
            "matrix_id": self.matrix_id,
            "manifest_sha256": self.manifest_sha256,
            "source_revision": self.source_revision,
            "harness_revision": self.harness_revision,
            "harness_runtime_sha256": self.harness_runtime_sha256,
            "toolchain_manifest_sha256": self.toolchain_manifest_sha256,
            "scenario_receipt_sha256s": list(
                self.scenario_receipt_sha256s
            ),
            "status": self.status,
            "failure_count": self.failure_count,
            "failed_scenario_ids": list(self.failed_scenario_ids),
            "missing_scenario_ids": list(self.missing_scenario_ids),
            "extra_scenario_ids": list(self.extra_scenario_ids),
            "inventory_complete": not (
                self.missing_scenario_ids or self.extra_scenario_ids
            ),
            "fingerprints_verified": passed,
            "restart_policies_verified": passed,
            "process_termination_verified": passed,
            "runtime_toolchain_verified": passed,
            "primary_checkout_unchanged": passed,
            "automatic_reexecution_absent": passed,
            "llm_evidence_absent": passed,
            "gate_transition_authorized": False,
            "closed": False,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "FaultMatrixVerificationReceipt":
        payload = _mapping(payload, "fault matrix verification receipt")
        fields = {
            "schema",
            "matrix_id",
            "manifest_sha256",
            "source_revision",
            "harness_revision",
            "harness_runtime_sha256",
            "toolchain_manifest_sha256",
            "scenario_receipt_sha256s",
            "status",
            "failure_count",
            "failed_scenario_ids",
            "missing_scenario_ids",
            "extra_scenario_ids",
            "inventory_complete",
            "fingerprints_verified",
            "restart_policies_verified",
            "process_termination_verified",
            "runtime_toolchain_verified",
            "primary_checkout_unchanged",
            "automatic_reexecution_absent",
            "llm_evidence_absent",
            "gate_transition_authorized",
            "closed",
        }
        if set(payload) != fields:
            raise FaultMatrixShapeError(
                "fault matrix verification fields are not exact"
            )
        if payload["schema"] != "daedalus-fault-matrix-verification/1":
            raise FaultMatrixShapeError("fault matrix verification schema is wrong")
        for field in ("gate_transition_authorized", "closed"):
            if payload[field] is not False:
                raise FaultMatrixShapeError(
                    f"fault matrix verification contains unsupported claim: {field}"
                )
        list_fields = (
            "scenario_receipt_sha256s",
            "failed_scenario_ids",
            "missing_scenario_ids",
            "extra_scenario_ids",
        )
        if any(type(payload[field]) is not list for field in list_fields):
            raise FaultMatrixShapeError(
                "fault matrix verification arrays must be exact lists"
            )
        result = cls(
            matrix_id=payload["matrix_id"],
            manifest_sha256=payload["manifest_sha256"],
            source_revision=payload["source_revision"],
            harness_revision=payload["harness_revision"],
            harness_runtime_sha256=payload["harness_runtime_sha256"],
            toolchain_manifest_sha256=payload["toolchain_manifest_sha256"],
            scenario_receipt_sha256s=tuple(
                payload["scenario_receipt_sha256s"]
            ),
            status=payload["status"],
            failed_scenario_ids=tuple(payload["failed_scenario_ids"]),
            missing_scenario_ids=tuple(payload["missing_scenario_ids"]),
            extra_scenario_ids=tuple(payload["extra_scenario_ids"]),
        )
        expected = result.to_dict()
        if dict(payload) != expected:
            raise FaultMatrixShapeError(
                "fault matrix verification derived claims disagree"
            )
        return result

    def to_fault_matrix_evidence(
        self,
        manifest: FaultMatrixManifest,
        receipts: Sequence[FaultScenarioReceipt],
        *,
        expected_source_revision: str,
        expected_harness_revision: str,
        expected_harness_runtime_sha256: str,
        expected_toolchain_manifest_sha256: str,
    ) -> FaultMatrixEvidence:
        exact = verify_fault_matrix_run(
            manifest,
            receipts,
            expected_source_revision=expected_source_revision,
            expected_harness_revision=expected_harness_revision,
            expected_harness_runtime_sha256=expected_harness_runtime_sha256,
            expected_toolchain_manifest_sha256=(
                expected_toolchain_manifest_sha256
            ),
        )
        if exact != self:
            raise FaultMatrixBindingError(
                "fault matrix projection receipt is not the exact verified run"
            )
        if self.status != "passed":
            raise FaultMatrixBindingError(
                "failed fault matrix cannot become passing Gate evidence"
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
    expected_harness_runtime_sha256: str,
    expected_toolchain_manifest_sha256: str,
) -> FaultMatrixVerificationReceipt:
    """Compare one exact harness run with one revision-pinned manifest."""

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
    harness_runtime = _exact_digest(
        expected_harness_runtime_sha256,
        "expected_harness_runtime_sha256",
    )
    toolchain_manifest = _exact_digest(
        expected_toolchain_manifest_sha256,
        "expected_toolchain_manifest_sha256",
    )
    if manifest.source_revision != source_revision:
        raise FaultMatrixBindingError(
            "manifest is pinned to a different source revision"
        )
    if type(receipts) is not tuple:
        raise FaultMatrixShapeError("receipts must be an exact tuple")
    if any(type(item) is not FaultScenarioReceipt for item in receipts):
        raise FaultMatrixShapeError(
            "receipts must contain exact FaultScenarioReceipt"
        )

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
    artifacts = tuple(item.run_artifact_sha256 for item in receipts)
    if len(artifacts) != len(set(artifacts)):
        raise FaultMatrixBindingError("run artifacts must be unique per scenario")

    spec_by_id = {item.scenario_id: item for item in manifest.scenarios}
    expected_ids = set(spec_by_id)
    observed_ids = set(receipt_by_id)
    missing = tuple(sorted(expected_ids - observed_ids))
    extra = tuple(sorted(observed_ids - expected_ids))
    failed: list[str] = []

    for scenario_id in sorted(expected_ids.intersection(observed_ids)):
        spec = spec_by_id[scenario_id]
        receipt = receipt_by_id[scenario_id]
        observed_markers = set(receipt.durable_markers)
        passed = (
            receipt.scenario_spec_sha256 == spec.digest
            and receipt.source_revision == source_revision
            and receipt.harness_revision == harness_revision
            and receipt.harness_runtime_sha256 == harness_runtime
            and receipt.toolchain_manifest_sha256 == toolchain_manifest
            and receipt.injection_fingerprint_sha256
            == manifest.injection_fingerprint(spec)
            and receipt.observed_outcome == spec.expected_outcome
            and receipt.observed_restart_policy == spec.restart_policy
            and receipt.process_termination_observed
            is spec.process_termination
            and set(spec.expected_durable_markers).issubset(observed_markers)
            and set(spec.forbidden_durable_markers).isdisjoint(
                observed_markers
            )
            and receipt.primary_checkout_before_sha256
            == receipt.primary_checkout_after_sha256
            and receipt.automatic_reexecution_performed is False
            and receipt.llm_evidence_used is False
        )
        if not passed:
            failed.append(scenario_id)

    blockers = tuple(sorted(failed)) + missing + extra
    return FaultMatrixVerificationReceipt(
        matrix_id=manifest.matrix_id,
        manifest_sha256=manifest.digest,
        source_revision=source_revision,
        harness_revision=harness_revision,
        harness_runtime_sha256=harness_runtime,
        toolchain_manifest_sha256=toolchain_manifest,
        scenario_receipt_sha256s=tuple(
            sorted(item.digest for item in receipts)
        ),
        status="passed" if not blockers else "failed",
        failed_scenario_ids=tuple(sorted(failed)),
        missing_scenario_ids=missing,
        extra_scenario_ids=extra,
    )


__all__ = [
    "FINGERPRINT_ALGORITHM",
    "FaultMatrixBindingError",
    "FaultMatrixContractError",
    "FaultMatrixManifest",
    "FaultMatrixShapeError",
    "FaultMatrixVerificationReceipt",
    "FaultScenarioReceipt",
    "FaultScenarioSpec",
    "fault_injection_fingerprint",
    "verify_fault_matrix_run",
]
