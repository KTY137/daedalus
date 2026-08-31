"""Canonical chip publication-graph verification.

The chip domain owns contract reconstruction and execution-plan interpretation.
Kernel lease and terminal-authority facts are consumed read-only; this module
cannot issue a lease or start an EDA process.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Mapping

from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.effect_replay import inspect_effect_execution
from daedalus.kernel.effects import EffectExecutionRequest, EffectTerminalReceipt
from daedalus.kernel.offload_lease import (
    _SHA256,
    _strict_canonical_record,
    _verify_chip_eda_terminal_bookkeeping,
)
from daedalus.schemas import (
    AttemptContract,
    ContractProvenance,
    EvidencePacket,
    MissionContract,
    PolicyDecision,
    RuntimeManifest,
)
from daedalus.kernel.events.envelope import canonical_json
from daedalus.storage import ArtifactStore

from .contracts import (
    ChipArtifact,
    ChipRunReceipt,
    build_chip_contracts,
    build_chip_runtime_manifest,
    build_evidence_packet,
)
from .execution_plan import EdaExecutionPlan
from .executor import recover_retained_execution
from .publication import derive_chip_publication


def verify_chip_eda_publication_graph(
    *,
    authority_root: str | Path,
    source_revision: str,
    authorization: NonRuntimeEffectAuthorization,
    execution: EffectExecutionRequest,
    terminal_receipt: EffectTerminalReceipt,
    artifact_store: Any,
    phase: str,
    publication_adapter_sha256: str,
    raw_execution_receipt_sha256: str,
    raw_execution_receipt_locator: str,
    chip_receipt_sha256: str,
    chip_receipt_locator: str,
    evidence_packet_sha256: str,
    evidence_packet_locator: str,
) -> dict[str, Any]:
    """Verify the one non-promoting chip publication graph used by create/replay.

    The producer and restart path deliberately share this verifier.  A graph
    accepted here must therefore remain acceptable after process restart; an
    incomplete artifact role set or an inflated Evidence claim is refused
    before the discoverable publication index can be written.
    """

    evidence_root = _verify_chip_eda_terminal_bookkeeping(
        authority_root=authority_root,
        source_revision=source_revision,
        authorization=authorization,
        execution=execution,
        terminal_receipt=terminal_receipt,
    )
    if type(artifact_store) is not ArtifactStore:
        raise TypeError("chip publication verification requires canonical ArtifactStore")
    expected_store = (evidence_root / "artifacts").resolve(strict=False)
    observed_store = Path(artifact_store.root).resolve(strict=False)
    if os.path.normcase(str(expected_store)) != os.path.normcase(str(observed_store)):
        raise ValueError("chip publication artifact store is outside its authority")
    if str(phase) not in {"inspect", "synth", "impl"}:
        raise ValueError("chip publication phase is invalid")
    if not _SHA256.fullmatch(str(publication_adapter_sha256)):
        raise ValueError("chip publication adapter identity is invalid")

    replay = inspect_effect_execution(authorization, execution)
    if replay is None or replay.pending_reconciliation or replay.terminal_receipt is None:
        raise ValueError("chip publication has no exact durable terminal execution")
    retained = recover_retained_execution(
        artifact_store=artifact_store,
        execution=execution,
        start_receipt=replay.start_receipt,
        terminal_receipt=replay.terminal_receipt,
    )
    result = retained.result
    plan = retained.plan
    if (
        replay.terminal_receipt.to_dict() != terminal_receipt.to_dict()
        or result.receipt_sha256 != str(raw_execution_receipt_sha256)
        or result.receipt_locator != str(raw_execution_receipt_locator)
        or plan.phase != str(phase)
        or plan.digest != execution.operation_sha256
        or plan.publication_adapter_sha256 != str(publication_adapter_sha256)
    ):
        raise ValueError("raw EDA receipt is not bound to the publication authority")
    derivation = derive_chip_publication(result, plan, artifact_store)

    def retained_json(
        locator_uri: str,
        digest: str,
        *,
        kind: str,
        label: str,
    ) -> tuple[dict[str, Any], Any, bytes]:
        prefix = "artifact-locator:sha256:"
        if not str(locator_uri).startswith(prefix):
            raise ValueError(f"{label} locator is invalid")
        locator = artifact_store.verify(
            artifact_store.load_locator(str(locator_uri)[len(prefix) :])
        )
        if (
            locator.artifact_sha256 != str(digest)
            or locator.metadata.get("kind") != kind
        ):
            raise ValueError(f"{label} locator binding is invalid")
        payload = artifact_store.get_bytes(locator.artifact_sha256)
        return _strict_canonical_record(payload, label=label), locator, payload

    chip_body, chip_locator, chip_payload = retained_json(
        str(chip_receipt_locator),
        str(chip_receipt_sha256),
        kind="chip_run_receipt",
        label="chip run receipt",
    )
    evidence_body, evidence_locator, evidence_payload = retained_json(
        str(evidence_packet_locator),
        str(evidence_packet_sha256),
        kind="chip_evidence_packet",
        label="chip evidence packet",
    )
    if (
        chip_locator.metadata.get("phase") != str(phase)
        or evidence_locator.metadata.get("phase") != str(phase)
    ):
        raise ValueError("chip publication artifact metadata names another phase")

    receipt_fields = {
        "schema",
        "run_id",
        "mission_id",
        "attempt_id",
        "phase",
        "source_revision",
        "manifest_sha256",
        "trusted_tcl_sha256",
        "tool",
        "execution",
        "effect_start",
        "effect_terminal",
        "artifacts",
        "metrics",
        "dimensions",
        "verdict",
        "limitations",
        "created_at",
        "security_boundary_claimed",
    }
    artifact_fields = {
        "name",
        "role",
        "artifact_sha256",
        "locator_sha256",
        "locator_uri",
        "byte_length",
        "media_type",
        "local_path",
    }
    raw_artifacts = chip_body.get("artifacts")
    if (
        set(chip_body) != receipt_fields
        or not isinstance(raw_artifacts, list)
        or not all(
            isinstance(row, Mapping) and set(row) == artifact_fields
            for row in raw_artifacts
        )
    ):
        raise ValueError("chip run receipt is structurally invalid")
    try:
        receipt = ChipRunReceipt(
            schema=chip_body["schema"],
            run_id=chip_body["run_id"],
            mission_id=chip_body["mission_id"],
            attempt_id=chip_body["attempt_id"],
            phase=chip_body["phase"],
            source_revision=chip_body["source_revision"],
            manifest_sha256=chip_body["manifest_sha256"],
            trusted_tcl_sha256=chip_body["trusted_tcl_sha256"],
            tool=chip_body["tool"],
            execution=chip_body["execution"],
            effect_start=chip_body["effect_start"],
            effect_terminal=chip_body["effect_terminal"],
            artifacts=tuple(ChipArtifact(**dict(row)) for row in raw_artifacts),
            metrics=chip_body["metrics"],
            dimensions=chip_body["dimensions"],
            verdict=chip_body["verdict"],
            limitations=tuple(chip_body["limitations"]),
            created_at=chip_body["created_at"],
            security_boundary_claimed=chip_body["security_boundary_claimed"],
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("chip run receipt contract is invalid") from exc
    if (
        receipt.to_json().encode("ascii") != chip_payload
        or receipt.digest != str(chip_receipt_sha256)
        or receipt.run_id != authorization.request.attempt_id
        or receipt.mission_id != authorization.request.mission_id
        or receipt.attempt_id != authorization.request.attempt_id
        or receipt.phase != str(phase)
        or receipt.source_revision != plan.source_manifest_sha256
        or receipt.manifest_sha256 != plan.source_manifest_sha256
        or receipt.trusted_tcl_sha256 != plan.trusted_tcl_sha256
        or receipt.verdict != derivation.verdict
        or canonical_json(receipt.dimensions)
        != canonical_json(derivation.dimensions)
        or tuple(receipt.limitations) != derivation.limitations
        or canonical_json(receipt.tool) != canonical_json(derivation.tool)
        or canonical_json(receipt.execution) != canonical_json(result.to_dict())
        or canonical_json(receipt.effect_start)
        != canonical_json(result.start_receipt.to_dict())
        or canonical_json(receipt.effect_terminal)
        != canonical_json(terminal_receipt.to_dict())
        or receipt.created_at != terminal_receipt.finished_at
    ):
        raise ValueError("chip run receipt is not bound to the terminal execution")
    metrics = receipt.metrics

    artifacts_by_role: dict[str, list[Any]] = {}
    allowed_roles = {
        "authoritative_manifest",
        "workspace_manifest",
        "trusted_tcl",
        "runtime_manifest",
        "execution_plan",
        "mission_contract",
        "attempt_contract",
        "policy_decision",
        "post_authoritative_manifest",
        "post_workspace_manifest",
        "vivado_native_output",
        "vivado_unexpected_output",
        "console_stdout",
        "console_stderr",
        "execution_receipt",
    }
    for artifact in receipt.artifacts:
        if artifact.role not in allowed_roles:
            raise ValueError(f"chip receipt contains unsupported artifact role {artifact.role!r}")
        locator = artifact_store.verify(
            artifact_store.load_locator(artifact.locator_sha256)
        )
        locator_manifest = locator.to_dict()
        if (
            locator.locator_uri != artifact.locator_uri
            or locator.artifact_sha256 != artifact.artifact_sha256
            or locator.byte_length != artifact.byte_length
            or locator_manifest.get("media_type") != artifact.media_type
            or (
                artifact.role
                not in {"vivado_native_output", "vivado_unexpected_output"}
                and artifact.local_path
            )
        ):
            raise ValueError("chip receipt artifact locator is invalid")
        if artifact.role in {
            "runtime_manifest",
            "execution_plan",
            "mission_contract",
            "attempt_contract",
            "policy_decision",
        } and locator.metadata.get("kind") != artifact.role:
            raise ValueError("chip receipt canonical artifact role is invalid")
        artifacts_by_role.setdefault(artifact.role, []).append(artifact)

    def one(role: str) -> Any:
        rows = artifacts_by_role.get(role, [])
        if len(rows) != 1:
            raise ValueError(f"chip receipt requires exactly one {role} artifact role")
        return rows[0]

    fixed_bindings = {
        "authoritative_manifest": (
            "source-manifest.json",
            plan.source_manifest_sha256,
            result.pre_authoritative_manifest_locator,
        ),
        "workspace_manifest": (
            "workspace-manifest.json",
            plan.workspace_manifest_sha256,
            result.pre_workspace_manifest_locator,
        ),
        "trusted_tcl": (
            "vivado_project_flow.tcl",
            plan.trusted_tcl_sha256,
            result.trusted_tcl_locator,
        ),
        "execution_receipt": (
            "eda-execution-receipt.json",
            result.receipt_sha256,
            result.receipt_locator,
        ),
        "console_stdout": (
            "vivado-stdout.log",
            result.stdout_sha256,
            result.stdout_locator,
        ),
        "console_stderr": (
            "vivado-stderr.log",
            result.stderr_sha256,
            result.stderr_locator,
        ),
    }
    for role, (name, digest, locator_uri) in fixed_bindings.items():
        artifact = one(role)
        if (
            artifact.name != name
            or artifact.artifact_sha256 != digest
            or artifact.locator_uri != locator_uri
            or artifact.local_path
        ):
            raise ValueError(f"chip receipt {role} artifact binding is invalid")

    for role, name, digest, locator_uri in (
        (
            "post_authoritative_manifest",
            "post-source-manifest.json",
            result.post_authoritative_manifest_sha256,
            result.post_authoritative_manifest_locator,
        ),
        (
            "post_workspace_manifest",
            "post-workspace-manifest.json",
            result.post_workspace_manifest_sha256,
            result.post_workspace_manifest_locator,
        ),
    ):
        rows = artifacts_by_role.get(role, [])
        if digest is None and locator_uri is None:
            if rows:
                raise ValueError(f"chip receipt has an unbound {role} artifact")
        else:
            artifact = one(role)
            if (
                artifact.name != name
                or artifact.artifact_sha256 != digest
                or artifact.locator_uri != locator_uri
                or artifact.local_path
            ):
                raise ValueError(f"chip receipt {role} artifact binding is invalid")

    expected_native = {
        (
            Path(artifact.path).name,
            artifact.path,
            artifact.sha256,
            artifact.locator,
            artifact.byte_length,
            (
                "vivado_unexpected_output"
                if artifact.path in set(result.unexpected_artifact_paths)
                else "vivado_native_output"
            ),
        )
        for artifact in result.artifacts
    }
    observed_native = {
        (
            artifact.name,
            artifact.local_path,
            artifact.artifact_sha256,
            artifact.locator_uri,
            artifact.byte_length,
            artifact.role,
        )
        for role in ("vivado_native_output", "vivado_unexpected_output")
        for artifact in artifacts_by_role.get(role, [])
    }
    if expected_native != observed_native or len(expected_native) != len(
        artifacts_by_role.get("vivado_native_output", [])
        + artifacts_by_role.get("vivado_unexpected_output", [])
    ):
        raise ValueError("chip receipt native artifact inventory is incomplete")

    def typed_artifact(role: str, contract_type: Any) -> Any:
        artifact = one(role)
        payload = artifact_store.get_bytes(artifact.artifact_sha256)
        body = _strict_canonical_record(payload, label=f"chip {role} artifact")
        value = contract_type.from_dict(body)
        if value.to_json().encode("ascii") != payload or value.digest != artifact.artifact_sha256:
            raise ValueError(f"chip receipt {role} contract bytes are invalid")
        return value

    execution_plan_artifact = one("execution_plan")
    execution_plan_payload = artifact_store.get_bytes(
        execution_plan_artifact.artifact_sha256
    )
    execution_plan_body = _strict_canonical_record(
        execution_plan_payload,
        label="chip execution plan artifact",
    )
    retained_plan = EdaExecutionPlan.from_dict(execution_plan_body)
    if (
        execution_plan_artifact.name != "eda-execution-plan.json"
        or retained_plan.to_dict() != plan.to_dict()
        or retained_plan.digest != execution_plan_artifact.artifact_sha256
        or canonical_json(retained_plan.to_dict()).encode("ascii")
        != execution_plan_payload
    ):
        raise ValueError("chip receipt execution_plan artifact is invalid")

    policy = typed_artifact("policy_decision", PolicyDecision)
    runtime = typed_artifact("runtime_manifest", RuntimeManifest)
    mission = typed_artifact("mission_contract", MissionContract)
    attempt = typed_artifact("attempt_contract", AttemptContract)
    expected_runtime = build_chip_runtime_manifest(
        source_revision=str(source_revision),
        trusted_tcl_sha256=plan.trusted_tcl_sha256,
        launcher_sha256=plan.launcher_sha256,
        execution_plan_sha256=plan.digest,
        created_at=terminal_receipt.finished_at,
    )
    expected_mission, expected_attempt = build_chip_contracts(
        mission_id=authorization.request.mission_id,
        attempt_id=authorization.request.attempt_id,
        phase=str(phase),
        manifest_sha256=plan.source_manifest_sha256,
        trusted_tcl_sha256=plan.trusted_tcl_sha256,
        runtime_manifest_sha256=expected_runtime.digest,
        policy_decision_sha256=authorization.policy_decision.digest,
        policy_sha256=authorization.policy_decision.policy_sha256,
        timeout_s=max(1, int(math.ceil(float(plan.timeout_s)))),
        created_at=terminal_receipt.finished_at,
    )
    expected_publication_metrics = derivation.metrics(
        runtime_manifest_sha256=expected_runtime.digest
    )
    if canonical_json(metrics) != canonical_json(expected_publication_metrics):
        raise ValueError(
            "chip run receipt summary, reports, messages, artifact binding, "
            "or manifest metrics contradict retained CAS evidence"
        )
    if (
        one("policy_decision").name != "policy-decision.json"
        or policy.to_dict() != authorization.policy_decision.to_dict()
        or one("runtime_manifest").name != "runtime-manifest.json"
        or runtime.to_dict() != expected_runtime.to_dict()
        or metrics.get("runtime_manifest_sha256") != expected_runtime.digest
        or one("mission_contract").name != "mission.json"
        or mission.to_dict() != expected_mission.to_dict()
        or one("attempt_contract").name != "attempt.json"
        or attempt.to_dict() != expected_attempt.to_dict()
    ):
        raise ValueError("chip receipt canonical contract artifact graph is invalid")

    common_inputs = {
        plan.source_manifest_sha256,
        plan.workspace_manifest_sha256,
        plan.trusted_tcl_sha256,
        expected_runtime.digest,
        plan.digest,
        result.receipt_sha256,
    }
    for digest in (
        result.post_authoritative_manifest_sha256,
        result.post_workspace_manifest_sha256,
    ):
        if digest is not None:
            common_inputs.add(digest)
    common_provenance = ContractProvenance(
        origin="daedalus.chip_design.cli",
        source_revision=plan.source_identity_sha256,
        created_at=terminal_receipt.finished_at,
        input_digests=tuple(sorted(common_inputs)),
    ).to_dict()
    canonical_locator_bindings = {
        "runtime_manifest": expected_runtime.provenance.to_dict(),
        "execution_plan": common_provenance,
        "mission_contract": expected_mission.provenance.to_dict(),
        "attempt_contract": expected_attempt.provenance.to_dict(),
        "policy_decision": authorization.policy_decision.provenance.to_dict(),
    }
    for role, expected_provenance in canonical_locator_bindings.items():
        artifact = one(role)
        locator = artifact_store.verify(
            artifact_store.load_locator(artifact.locator_sha256)
        )
        if (
            locator.metadata
            != {"kind": role, "filename_hint": artifact.name}
            or locator.provenance != expected_provenance
        ):
            raise ValueError(
                f"chip receipt {role} locator metadata or provenance is invalid"
            )

    try:
        evidence = EvidencePacket.from_dict(evidence_body)
    except (TypeError, ValueError) as exc:
        raise ValueError("chip evidence packet contract is invalid") from exc
    expected_evidence = build_evidence_packet(
        receipt=receipt,
        receipt_locator=chip_locator,
        attempt=expected_attempt,
        policy_decision_sha256=authorization.policy_decision.digest,
    )
    receipt_inputs = {
        expected_attempt.digest,
        plan.source_manifest_sha256,
        plan.workspace_manifest_sha256,
        expected_runtime.digest,
        plan.digest,
        plan.trusted_tcl_sha256,
        authorization.policy_decision.digest,
        *(artifact.artifact_sha256 for artifact in receipt.artifacts),
    }
    expected_receipt_provenance = ContractProvenance(
        origin="daedalus.chip_design.cli",
        source_revision=receipt.source_revision,
        created_at=receipt.created_at,
        input_digests=tuple(sorted(receipt_inputs)),
    ).to_dict()
    item = evidence.items[0] if len(evidence.items) == 1 else None
    expected_item_verdict = {
        "failed": "failed",
        "cancelled": "cancelled",
        "error": "error",
    }.get(receipt.verdict, "passed")
    if (
        evidence.to_json().encode("ascii") != evidence_payload
        or evidence.digest != str(evidence_packet_sha256)
        or evidence.to_dict() != expected_evidence.to_dict()
        or chip_locator.metadata
        != {
            "kind": "chip_run_receipt",
            "phase": str(phase),
            "filename_hint": f"{receipt.run_id}-chip-receipt.json",
        }
        or chip_locator.provenance != expected_receipt_provenance
        or evidence_locator.metadata
        != {
            "kind": "chip_evidence_packet",
            "phase": str(phase),
            "filename_hint": f"{receipt.run_id}-evidence.json",
        }
        or evidence_locator.provenance != expected_evidence.provenance.to_dict()
        or evidence.packet_id != f"{receipt.run_id}-evidence"
        or evidence.mission_id != authorization.request.mission_id
        or evidence.attempt_id != authorization.request.attempt_id
        or evidence.source_revision != receipt.source_revision
        or evidence.subject_sha256 != receipt.manifest_sha256
        or evidence.policy_decision_sha256 != authorization.policy_decision.digest
        or evidence.evaluation_status != "inconclusive"
        or evidence.attempt_contract_sha256 != attempt.digest
        or item is None
        or item.evidence_id != f"{receipt.run_id}-vivado"
        or item.evaluator != "vivado-project"
        or item.assurance != "unverified"
        or item.verdict != expected_item_verdict
        or item.output_sha256 != receipt.digest
        or item.evidence_locator != chip_locator.locator_uri
        or item.collected_at != terminal_receipt.finished_at
        or evidence.usage.wall_time_ms
        != max(0, int(round(float(result.duration_s) * 1000)))
        or dict(item.details)
        != {
            "phase": str(phase),
            "chip_verdict": receipt.verdict,
            "dimensions": dict(receipt.dimensions),
            "security_boundary_claimed": False,
        }
    ):
        raise ValueError("chip evidence packet inflates or contradicts its receipt")

    return {
        "retained_execution": retained,
        "receipt": receipt,
        "receipt_locator": chip_locator,
        "evidence": evidence,
        "evidence_locator": evidence_locator,
    }

__all__ = ["verify_chip_eda_publication_graph"]
