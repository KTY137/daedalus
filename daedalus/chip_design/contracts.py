"""Canonical contract and receipt helpers for admitted chip-design runs.

These records add no policy or storage authority. They bind the existing
Mission, Attempt, Effect-Lease, ArtifactStore, and Evidence contracts around a
hardware-specific result so native EDA reports do not collapse into one exit
code.
"""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from daedalus.schemas import (
    AttemptContract,
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
    MissionContract,
    ResourceBudget,
    ResourceUsage,
    RuntimeCapabilities,
    RuntimeManifest,
    derive_work_item_id,
)
from daedalus.spine.envelope import canonical_json, canonical_sha
from daedalus.storage import ArtifactLocator


CHIP_RUN_SCHEMA = "daedalus-chip-run/1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERDICTS = frozenset({"passed", "failed", "error", "cancelled", "inconclusive"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _digest(value: str, label: str) -> str:
    text = str(value)
    if not _SHA256.fullmatch(text):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


@dataclass(frozen=True)
class ChipArtifact:
    """One native or normalized EDA output retained by ``ArtifactStore``."""

    name: str
    role: str
    artifact_sha256: str
    locator_sha256: str
    locator_uri: str
    byte_length: int
    media_type: str
    local_path: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.role.strip():
            raise ValueError("chip artifact name and role must be non-empty")
        _digest(self.artifact_sha256, "artifact_sha256")
        locator = _digest(self.locator_sha256, "locator_sha256")
        if self.locator_uri != f"artifact-locator:sha256:{locator}":
            raise ValueError("chip artifact locator URI does not match locator digest")
        if isinstance(self.byte_length, bool) or self.byte_length < 0:
            raise ValueError("chip artifact byte_length must be non-negative")
        if not self.media_type.strip():
            raise ValueError("chip artifact media_type must be non-empty")

    @classmethod
    def from_locator(
        cls,
        *,
        name: str,
        role: str,
        locator: ArtifactLocator,
        media_type: str,
        local_path: str = "",
    ) -> "ChipArtifact":
        return cls(
            name=name,
            role=role,
            artifact_sha256=locator.artifact_sha256,
            locator_sha256=locator.locator_sha256,
            locator_uri=locator.locator_uri,
            byte_length=locator.byte_length,
            media_type=media_type,
            local_path=local_path,
        )

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class ChipRunReceipt:
    """Hardware-specific projection over canonical execution/evidence facts."""

    run_id: str
    mission_id: str
    attempt_id: str
    phase: str
    source_revision: str
    manifest_sha256: str
    trusted_tcl_sha256: str
    tool: Mapping[str, Any]
    execution: Mapping[str, Any]
    effect_start: Mapping[str, Any] | None
    effect_terminal: Mapping[str, Any] | None
    artifacts: tuple[ChipArtifact, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    dimensions: Mapping[str, str] = field(default_factory=dict)
    verdict: str = "inconclusive"
    limitations: tuple[str, ...] = ()
    created_at: str = field(default_factory=utc_now)
    schema: str = CHIP_RUN_SCHEMA
    security_boundary_claimed: bool = False

    def __post_init__(self) -> None:
        if self.schema != CHIP_RUN_SCHEMA:
            raise ValueError(f"unsupported chip run schema: {self.schema}")
        for label in ("run_id", "mission_id", "attempt_id", "phase"):
            if not str(getattr(self, label)).strip():
                raise ValueError(f"{label} must be non-empty")
        _digest(self.source_revision, "source_revision")
        _digest(self.manifest_sha256, "manifest_sha256")
        _digest(self.trusted_tcl_sha256, "trusted_tcl_sha256")
        if self.verdict not in _VERDICTS:
            raise ValueError(f"unsupported chip run verdict: {self.verdict}")
        if self.security_boundary_claimed:
            raise ValueError("the host EDA adapter is not an operating-system sandbox")
        object.__setattr__(self, "artifacts", tuple(sorted(self.artifacts, key=lambda row: row.name)))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))
        object.__setattr__(self, "tool", dict(self.tool))
        object.__setattr__(self, "execution", dict(self.execution))
        object.__setattr__(self, "metrics", dict(self.metrics))
        object.__setattr__(self, "dimensions", dict(sorted(self.dimensions.items())))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "mission_id": self.mission_id,
            "attempt_id": self.attempt_id,
            "phase": self.phase,
            "source_revision": self.source_revision,
            "manifest_sha256": self.manifest_sha256,
            "trusted_tcl_sha256": self.trusted_tcl_sha256,
            "tool": dict(self.tool),
            "execution": dict(self.execution),
            "effect_start": None if self.effect_start is None else dict(self.effect_start),
            "effect_terminal": None if self.effect_terminal is None else dict(self.effect_terminal),
            "artifacts": [row.to_dict() for row in self.artifacts],
            "metrics": dict(self.metrics),
            "dimensions": dict(self.dimensions),
            "verdict": self.verdict,
            "limitations": list(self.limitations),
            "created_at": self.created_at,
            "security_boundary_claimed": False,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


def build_chip_contracts(
    *,
    mission_id: str,
    attempt_id: str,
    phase: str,
    manifest_sha256: str,
    trusted_tcl_sha256: str,
    runtime_manifest_sha256: str,
    policy_decision_sha256: str,
    policy_sha256: str,
    timeout_s: int,
    created_at: str,
) -> tuple[MissionContract, AttemptContract]:
    """Build the canonical Mission/Attempt pair for one exact project phase."""

    source_revision = _digest(manifest_sha256, "manifest_sha256")
    task_sha256 = canonical_sha(
        {
            "schema": "daedalus-chip-task/1",
            "manifest_sha256": source_revision,
            "phase": phase,
            "trusted_tcl_sha256": _digest(trusted_tcl_sha256, "trusted_tcl_sha256"),
        }
    )
    budget = ResourceBudget(max_wall_time_s=max(1, int(timeout_s)), max_attempts=1)
    work_item_id = derive_work_item_id(
        mission_id,
        ordinal=1,
        identity=(phase, source_revision, trusted_tcl_sha256),
    )
    mission = MissionContract(
        mission_id=mission_id,
        objective=f"Run the admitted Vivado {phase} phase for exact manifest {source_revision}",
        source_revision=source_revision,
        work_item_ids=(work_item_id,),
        success_criteria=(
            "effect terminal is retained",
            "native reports are content-addressed",
            "unrun verification dimensions remain explicit",
        ),
        policy_sha256=_digest(policy_sha256, "policy_sha256"),
        budget=budget,
        provenance=ContractProvenance(
            origin="daedalus.chip_design",
            source_revision=source_revision,
            created_at=created_at,
            input_digests=(policy_sha256,),
        ),
    )
    attempt_inputs = tuple(
        sorted(
            {
                task_sha256,
                _digest(runtime_manifest_sha256, "runtime_manifest_sha256"),
                _digest(policy_decision_sha256, "policy_decision_sha256"),
            }
        )
    )
    attempt = AttemptContract(
        attempt_id=attempt_id,
        mission_id=mission_id,
        task_id=work_item_id,
        instruction=f"Execute package-owned Vivado {phase} flow for the bound XPR manifest",
        base_revision=source_revision,
        task_sha256=task_sha256,
        runtime_manifest_sha256=runtime_manifest_sha256,
        policy_decision_sha256=policy_decision_sha256,
        budget=budget,
        provenance=ContractProvenance(
            origin="daedalus.chip_design",
            source_revision=source_revision,
            created_at=created_at,
            input_digests=attempt_inputs,
        ),
        writable_paths=(".",),
        gate_names=("vivado-project",),
        read_only=False,
    )
    return mission, attempt


def build_chip_runtime_manifest(
    *,
    source_revision: str,
    trusted_tcl_sha256: str,
    launcher_sha256: str,
    execution_plan_sha256: str,
    created_at: str,
) -> RuntimeManifest:
    """Declare the actual local Vivado adapter separately from its operation.

    ``AttemptContract.runtime_manifest_sha256`` names this canonical contract;
    the phase-specific :class:`EdaExecutionPlan` remains independently bound
    as the lease/request ``operation_sha256`` and is never substituted for a
    runtime-manifest digest.
    """

    tcl_digest = _digest(trusted_tcl_sha256, "trusted_tcl_sha256")
    launcher_digest = _digest(launcher_sha256, "launcher_sha256")
    plan_digest = _digest(execution_plan_sha256, "execution_plan_sha256")
    return RuntimeManifest(
        runtime_id="amd-vivado-local",
        runtime_version=f"launcher-sha256-{launcher_digest[:16]}",
        adapter_id="daedalus-chip-vivado-project-flow",
        adapter_version=f"tcl-sha256-{tcl_digest[:16]}",
        source_revision=source_revision,
        assurance="declared",
        capabilities=RuntimeCapabilities(
            timeout=True,
            cancellation=True,
            workspace_isolation=True,
            workspace_write=True,
        ),
        declared_tools=(),
        egress_transports=(),
        workspace_modes=("isolated-worktree",),
        cost_model="not-applicable",
        provenance=ContractProvenance(
            origin="daedalus.chip_design.runtime-manifest",
            source_revision=source_revision,
            created_at=created_at,
            input_digests=(launcher_digest, plan_digest, tcl_digest),
        ),
    )


def build_evidence_packet(
    *,
    receipt: ChipRunReceipt,
    receipt_locator: ArtifactLocator,
    attempt: AttemptContract,
    policy_decision_sha256: str,
) -> EvidencePacket:
    """Project one chip receipt into canonical Evidence without signoff inflation."""

    execution_status = str(receipt.execution.get("status", "error"))
    if receipt.verdict == "failed":
        item_verdict = "failed"
        evaluation = "inconclusive"
    elif receipt.verdict == "cancelled" or execution_status == "timeout":
        item_verdict = "cancelled"
        evaluation = "inconclusive"
    elif receipt.verdict == "error":
        item_verdict = "error"
        evaluation = "inconclusive"
    else:
        item_verdict = "passed"
        # A successful build is useful deterministic evidence, but this slice
        # deliberately leaves simulation/CDC/equivalence/HIL/signoff unrun.
        evaluation = "inconclusive"

    locator_uri = receipt_locator.locator_uri
    item_inputs = tuple(sorted({receipt_locator.artifact_sha256, receipt_locator.locator_sha256}))
    item = EvidenceItem(
        evidence_id=f"{receipt.run_id}-vivado",
        evaluator="vivado-project",
        assurance="unverified",
        verdict=item_verdict,
        output_sha256=receipt_locator.artifact_sha256,
        evidence_locator=locator_uri,
        collected_at=receipt.created_at,
        provenance=ContractProvenance(
            origin="daedalus.chip_design",
            source_revision=receipt.source_revision,
            created_at=receipt.created_at,
            input_digests=item_inputs,
        ),
        details={
            "phase": receipt.phase,
            "chip_verdict": receipt.verdict,
            "dimensions": dict(receipt.dimensions),
            "security_boundary_claimed": False,
        },
    )
    packet_inputs = tuple(
        sorted(
            {
                attempt.digest,
                receipt.manifest_sha256,
                _digest(policy_decision_sha256, "policy_decision_sha256"),
                item.output_sha256,
            }
        )
    )
    duration_ms = max(0, int(round(float(receipt.execution.get("duration_s", 0.0)) * 1000)))
    return EvidencePacket(
        packet_id=f"{receipt.run_id}-evidence",
        mission_id=receipt.mission_id,
        attempt_id=receipt.attempt_id,
        source_revision=receipt.source_revision,
        attempt_contract_sha256=attempt.digest,
        subject_sha256=receipt.manifest_sha256,
        evaluation_status=evaluation,
        items=(item,),
        policy_decision_sha256=policy_decision_sha256,
        usage=ResourceUsage(wall_time_ms=duration_ms),
        provenance=ContractProvenance(
            origin="daedalus.chip_design",
            source_revision=receipt.source_revision,
            created_at=receipt.created_at,
            input_digests=packet_inputs,
        ),
    )


def default_dimensions(phase: str) -> dict[str, str]:
    dimensions = {
        "inventory": "passed",
        "lint": "not_run",
        "elaboration": "not_run",
        "simulation": "not_run",
        "formal": "not_run",
        "synthesis": "not_run",
        "implementation": "not_run",
        "timing": "not_run",
        "drc": "not_run",
        "methodology": "not_run",
        "cdc_rdc": "not_run",
        "equivalence": "not_run",
        "power": "not_run",
        "vitis_software": "not_run",
        "hardware_in_loop": "not_run",
        "signoff": "not_run",
    }
    if phase == "synth":
        dimensions["synthesis"] = "pending"
    elif phase == "impl":
        for name in ("synthesis", "implementation", "timing", "drc", "methodology"):
            dimensions[name] = "pending"
    return dimensions


__all__ = [
    "CHIP_RUN_SCHEMA",
    "ChipArtifact",
    "ChipRunReceipt",
    "build_chip_contracts",
    "build_chip_runtime_manifest",
    "build_evidence_packet",
    "default_dimensions",
    "utc_now",
]
