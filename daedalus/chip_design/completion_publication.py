"""Chip-owned terminal artifact retention and completion publication.

The kernel verifies the already-issued lease and terminal bookkeeping. This
module owns the chip-specific CAS roles, publication graph and projection bytes;
callers reach it through stable kernel effect facades with these implementations
injected explicitly.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.effects import EffectExecutionRequest, EffectTerminalReceipt
from daedalus.kernel.offload_lease import (
    CHIP_EDA_ENTRYPOINT_ID,
    CHIP_EDA_PUBLICATION_INDEX_SCHEMA,
    CHIP_EDA_PUBLICATION_RECORD_SCHEMA,
    _REVISION,
    _SHA256,
    _chip_publication_index_path,
    _publish_evidence_record,
    _publish_exact_bytes_once,
    _record_sha256,
    _stable_regular_bytes,
    _strict_canonical_record,
    _timestamp,
    _verify_chip_eda_terminal_bookkeeping,
    canonical_json,
    load_chip_eda_publication,
)

from .publication_verifier import verify_chip_eda_publication_graph


def retain_chip_eda_terminal_artifact(
    *,
    authority_root: str | Path,
    source_revision: str,
    authorization: NonRuntimeEffectAuthorization,
    execution: EffectExecutionRequest,
    terminal_receipt: EffectTerminalReceipt,
    artifact_store: Any,
    payload: bytes,
    expected_sha256: str,
    media_type: str,
    metadata: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> Any:
    """Retain one canonical-finalizer artifact under terminal authority.

    Private by design: only ``daedalus.chip_design.cli`` may compose this
    authority-root bookkeeping step, and the repository write-inventory gate
    pins those call sites.
    """

    from daedalus.storage import ArtifactStore

    evidence_root = _verify_chip_eda_terminal_bookkeeping(
        authority_root=authority_root,
        source_revision=source_revision,
        authorization=authorization,
        execution=execution,
        terminal_receipt=terminal_receipt,
    )
    if type(artifact_store) is not ArtifactStore:
        raise TypeError("chip terminal bookkeeping requires canonical ArtifactStore")
    expected_store = (evidence_root / "artifacts").resolve(strict=False)
    observed_store = Path(artifact_store.root).resolve(strict=False)
    if os.path.normcase(str(expected_store)) != os.path.normcase(str(observed_store)):
        raise ValueError("chip terminal artifact store is outside its authority root")
    allowed = {
        "runtime_manifest": "runtime-manifest.json",
        "execution_plan": "eda-execution-plan.json",
        "mission_contract": "mission.json",
        "attempt_contract": "attempt.json",
        "policy_decision": "policy-decision.json",
        "chip_run_receipt": None,
        "chip_evidence_packet": None,
    }
    kind = str(metadata.get("kind", ""))
    filename_hint = str(metadata.get("filename_hint", ""))
    phase = metadata.get("phase")
    expected_metadata_fields = (
        {"kind", "filename_hint", "phase"}
        if kind in {"chip_run_receipt", "chip_evidence_packet"}
        else {"kind", "filename_hint"}
    )
    if (
        set(metadata) != expected_metadata_fields
        or kind not in allowed
        or not filename_hint
        or (allowed[kind] is not None and filename_hint != allowed[kind])
        or (
            kind in {"chip_run_receipt", "chip_evidence_packet"}
            and phase not in {"inspect", "synth", "impl"}
        )
        or media_type != "application/json"
    ):
        raise ValueError("chip terminal artifact role is outside the fixed completion set")
    _strict_canonical_record(payload, label=f"chip terminal {kind} artifact")
    return artifact_store.put_bytes(
        payload,
        expected_sha256=expected_sha256,
        media_type=media_type,
        metadata=dict(metadata),
        provenance=dict(provenance),
    )


def record_chip_eda_publication(
    *,
    authority_root: str | Path,
    evidence_root: str | Path,
    source_revision: str,
    authorization: NonRuntimeEffectAuthorization,
    execution: EffectExecutionRequest,
    terminal_receipt: EffectTerminalReceipt,
    artifact_store: Any,
    phase: str,
    publication_adapter_sha256: str,
    lease_sha256: str,
    execution_id: str,
    execution_request_sha256: str,
    terminal_receipt_sha256: str,
    raw_execution_receipt_sha256: str,
    raw_execution_receipt_locator: str,
    chip_receipt_sha256: str,
    chip_receipt_locator: str,
    evidence_packet_sha256: str,
    evidence_packet_locator: str,
    authority_head_record_sha256: str,
    lease_subject_record_sha256: str,
    lease_execution_record_sha256: str,
    lease_terminal_record_sha256: str,
    finished_at: str,
) -> dict[str, Any]:
    """Publish the canonical finalizer's unique chip completion edge.

    Private by design. These bytes add no candidate authority: they are authority-root bookkeeping
    for the already-terminal ``cli.daedalus_chip`` entrypoint.  Every artifact
    named here was retained before this record and a restart republishes the
    identical content rather than starting Vivado again.
    """

    if not _REVISION.fullmatch(str(source_revision)):
        raise ValueError("chip publication source_revision must be lowercase 40-hex")
    expected_evidence_root = _verify_chip_eda_terminal_bookkeeping(
        authority_root=authority_root,
        source_revision=source_revision,
        authorization=authorization,
        execution=execution,
        terminal_receipt=terminal_receipt,
    )
    if os.path.normcase(str(Path(evidence_root).resolve(strict=False))) != os.path.normcase(
        str(expected_evidence_root.resolve(strict=False))
    ):
        raise ValueError("chip publication evidence root is outside its authority")
    from daedalus.storage import ArtifactStore

    if type(artifact_store) is not ArtifactStore:
        raise TypeError("chip publication requires the canonical ArtifactStore")
    if os.path.normcase(str(Path(artifact_store.root).resolve(strict=False))) != os.path.normcase(
        str((expected_evidence_root / "artifacts").resolve(strict=False))
    ):
        raise ValueError("chip publication artifact store is outside its authority")
    digests = {
        "lease_sha256": lease_sha256,
        "publication_adapter_sha256": publication_adapter_sha256,
        "execution_request_sha256": execution_request_sha256,
        "terminal_receipt_sha256": terminal_receipt_sha256,
        "raw_execution_receipt_sha256": raw_execution_receipt_sha256,
        "chip_receipt_sha256": chip_receipt_sha256,
        "evidence_packet_sha256": evidence_packet_sha256,
        "authority_head_record_sha256": authority_head_record_sha256,
        "lease_subject_record_sha256": lease_subject_record_sha256,
        "lease_execution_record_sha256": lease_execution_record_sha256,
        "lease_terminal_record_sha256": lease_terminal_record_sha256,
    }
    for label, digest in digests.items():
        if not _SHA256.fullmatch(str(digest)):
            raise ValueError(f"chip publication {label} must be a SHA-256 digest")
    locators = {
        "raw_execution_receipt_locator": raw_execution_receipt_locator,
        "chip_receipt_locator": chip_receipt_locator,
        "evidence_packet_locator": evidence_packet_locator,
    }
    for label, locator in locators.items():
        prefix = "artifact-locator:sha256:"
        if not str(locator).startswith(prefix) or not _SHA256.fullmatch(
            str(locator)[len(prefix) :]
        ):
            raise ValueError(f"chip publication {label} is invalid")
    try:
        timestamp = _timestamp(datetime.fromisoformat(str(finished_at).replace("Z", "+00:00")))
    except ValueError as exc:
        raise ValueError("chip publication finished_at must be ISO-8601") from exc
    if not str(execution_id).strip():
        raise ValueError("chip publication execution_id must be non-empty")
    if str(phase) not in {"inspect", "synth", "impl"}:
        raise ValueError("chip publication phase is invalid")
    if (
        str(lease_sha256) != authorization.lease.digest
        or str(execution_id) != execution.execution_id
        or str(execution_request_sha256) != execution.digest
        or str(terminal_receipt_sha256) != terminal_receipt.receipt_sha256
        or str(finished_at) != terminal_receipt.finished_at
    ):
        raise ValueError("chip publication arguments contradict terminal authority")

    verify_chip_eda_publication_graph(
        authority_root=authority_root,
        source_revision=source_revision,
        authorization=authorization,
        execution=execution,
        terminal_receipt=terminal_receipt,
        artifact_store=artifact_store,
        phase=phase,
        publication_adapter_sha256=publication_adapter_sha256,
        raw_execution_receipt_sha256=raw_execution_receipt_sha256,
        raw_execution_receipt_locator=raw_execution_receipt_locator,
        chip_receipt_sha256=chip_receipt_sha256,
        chip_receipt_locator=chip_receipt_locator,
        evidence_packet_sha256=evidence_packet_sha256,
        evidence_packet_locator=evidence_packet_locator,
    )

    def retained_json(
        locator_uri: str,
        digest: str,
        *,
        kind: str,
        label: str,
    ) -> tuple[dict[str, Any], Any]:
        locator_digest = str(locator_uri).removeprefix("artifact-locator:sha256:")
        locator = artifact_store.verify(artifact_store.load_locator(locator_digest))
        if (
            locator.artifact_sha256 != str(digest)
            or locator.metadata.get("kind") != kind
        ):
            raise ValueError(f"{label} locator binding is invalid")
        payload = artifact_store.get_bytes(locator.artifact_sha256)
        return _strict_canonical_record(payload, label=label), locator

    if str(raw_execution_receipt_sha256) not in terminal_receipt.output_digests:
        raise ValueError("raw EDA receipt is not bound by the terminal receipt")
    raw, raw_locator = retained_json(
        str(raw_execution_receipt_locator),
        str(raw_execution_receipt_sha256),
        kind="eda_execution_receipt",
        label="raw EDA execution receipt",
    )
    if raw_locator.metadata.get("execution_id") != execution.execution_id:
        raise ValueError("raw EDA receipt locator names another execution")
    from daedalus.chip_design.execution_plan import EdaExecutionPlan

    plan = EdaExecutionPlan.from_dict(raw.get("execution_plan"))
    raw_start = raw.get("effect_start_receipt")
    if (
        raw.get("schema") != "daedalus.eda-execution-receipt/3"
        or raw.get("execution_id") != execution.execution_id
        or raw.get("execution_request_sha256") != execution.digest
        or raw.get("operation_sha256") != execution.operation_sha256
        or plan.digest != execution.operation_sha256
        or plan.phase != str(phase)
        or plan.publication_adapter_sha256 != str(publication_adapter_sha256)
        or not isinstance(raw_start, Mapping)
        or raw_start.get("receipt_sha256") != terminal_receipt.start_receipt_sha256
    ):
        raise ValueError("raw EDA receipt is not bound to the publication plan")

    chip, chip_locator = retained_json(
        str(chip_receipt_locator),
        str(chip_receipt_sha256),
        kind="chip_run_receipt",
        label="chip run receipt",
    )
    evidence, evidence_locator = retained_json(
        str(evidence_packet_locator),
        str(evidence_packet_sha256),
        kind="chip_evidence_packet",
        label="chip evidence packet",
    )
    chip_execution = chip.get("execution")
    chip_tool = chip.get("tool")
    chip_metrics = chip.get("metrics")
    if (
        chip_locator.metadata.get("phase") != str(phase)
        or evidence_locator.metadata.get("phase") != str(phase)
        or chip.get("schema") != "daedalus-chip-run/1"
        or chip.get("mission_id") != authorization.request.mission_id
        or chip.get("attempt_id") != authorization.request.attempt_id
        or chip.get("phase") != str(phase)
        or chip.get("source_revision") != plan.source_manifest_sha256
        or chip.get("manifest_sha256") != plan.source_manifest_sha256
        or chip.get("trusted_tcl_sha256") != plan.trusted_tcl_sha256
        or chip.get("effect_start") != raw_start
        or chip.get("effect_terminal") != terminal_receipt.to_dict()
        or chip.get("created_at") != terminal_receipt.finished_at
        or chip.get("security_boundary_claimed") is not False
        or not isinstance(chip_execution, Mapping)
        or chip_execution.get("receipt_sha256") != str(raw_execution_receipt_sha256)
        or chip_execution.get("receipt_locator") != str(raw_execution_receipt_locator)
        or not isinstance(chip_tool, Mapping)
        or chip_tool.get("launcher_sha256") != plan.launcher_sha256
        or chip_tool.get("selected_command") != plan.argv[0]
        or not isinstance(chip_metrics, Mapping)
        or chip_metrics.get("execution_plan_sha256") != plan.digest
        or canonical_json(chip_metrics.get("execution_plan"))
        != canonical_json(plan.to_dict())
    ):
        raise ValueError("chip run receipt is not bound to the terminal execution")

    from daedalus.schemas import EvidencePacket

    typed_evidence = EvidencePacket.from_dict(evidence)
    items = typed_evidence.items
    if (
        typed_evidence.mission_id != authorization.request.mission_id
        or typed_evidence.attempt_id != authorization.request.attempt_id
        or typed_evidence.source_revision != plan.source_manifest_sha256
        or typed_evidence.subject_sha256 != plan.source_manifest_sha256
        or typed_evidence.policy_decision_sha256 != authorization.policy_decision.digest
        or len(items) != 1
        or items[0].output_sha256 != str(chip_receipt_sha256)
        or items[0].evidence_locator != str(chip_receipt_locator)
    ):
        raise ValueError("chip evidence packet is not bound to the chip receipt")

    artifacts = chip.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("chip receipt artifact inventory is invalid")
    artifacts_by_role: dict[str, list[Mapping[str, Any]]] = {}
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, Mapping):
            raise ValueError(f"chip receipt artifact {index} is invalid")
        locator_uri = str(artifact.get("locator_uri", ""))
        locator_digest = str(artifact.get("locator_sha256", ""))
        if locator_uri != f"artifact-locator:sha256:{locator_digest}":
            raise ValueError(f"chip receipt artifact {index} locator is invalid")
        locator = artifact_store.verify(artifact_store.load_locator(locator_digest))
        if (
            locator.artifact_sha256 != artifact.get("artifact_sha256")
            or locator.byte_length != artifact.get("byte_length")
        ):
            raise ValueError(f"chip receipt artifact {index} binding is invalid")
        artifacts_by_role.setdefault(str(artifact.get("role", "")), []).append(artifact)
    required_artifacts = {
        "execution_plan": plan.digest,
        "policy_decision": authorization.policy_decision.digest,
        "attempt_contract": typed_evidence.attempt_contract_sha256,
    }
    for role, expected_digest in required_artifacts.items():
        rows = artifacts_by_role.get(role, [])
        if len(rows) != 1 or rows[0].get("artifact_sha256") != expected_digest:
            raise ValueError(f"chip receipt {role} artifact is not uniquely bound")

    def authority_record(kind: str, digest: str) -> dict[str, Any]:
        path = expected_evidence_root / kind / f"{digest}.json"
        retained = _strict_canonical_record(
            _stable_regular_bytes(path, label=f"{kind} authority record"),
            label=f"{kind} authority record",
        )
        if retained.get("record_sha256") != digest or _record_sha256(retained) != digest:
            raise ValueError(f"{kind} authority record digest is invalid")
        return retained

    head = authority_record("authority-head", str(authority_head_record_sha256))
    subject = authority_record("lease-subject", str(lease_subject_record_sha256))
    execution_record = authority_record(
        "lease-execution", str(lease_execution_record_sha256)
    )
    terminal_record = authority_record(
        "lease-terminal", str(lease_terminal_record_sha256)
    )
    repository_head = head.get("repository_head_receipt")
    if (
        head.get("entrypoint_id") != CHIP_EDA_ENTRYPOINT_ID
        or head.get("lease_sha256") != authorization.lease.digest
        or head.get("operation_sha256") != execution.operation_sha256
        or not isinstance(repository_head, Mapping)
        or repository_head.get("expected_revision") != str(source_revision)
        or subject.get("source_revision") != str(source_revision)
        or subject.get("lease_sha256") != authorization.lease.digest
        or execution_record.get("source_revision") != str(source_revision)
        or execution_record.get("execution_id") != execution.execution_id
        or execution_record.get("execution_request_sha256") != execution.digest
        or execution_record.get("subject_record_sha256")
        != str(lease_subject_record_sha256)
        or terminal_record.get("source_revision") != str(source_revision)
        or terminal_record.get("execution_id") != execution.execution_id
        or terminal_record.get("execution_request_sha256") != execution.digest
        or terminal_record.get("receipt_sha256")
        != terminal_receipt.receipt_sha256
    ):
        raise ValueError("chip publication authority records are not cross-bound")
    body: dict[str, Any] = {
        "schema": CHIP_EDA_PUBLICATION_RECORD_SCHEMA,
        "source_revision": str(source_revision),
        "entrypoint_id": CHIP_EDA_ENTRYPOINT_ID,
        "phase": str(phase),
        "publication_adapter_sha256": str(publication_adapter_sha256),
        "lease_sha256": str(lease_sha256),
        "execution_id": str(execution_id),
        "execution_request_sha256": str(execution_request_sha256),
        "terminal_receipt_sha256": str(terminal_receipt_sha256),
        "raw_execution_receipt_sha256": str(raw_execution_receipt_sha256),
        "raw_execution_receipt_locator": str(raw_execution_receipt_locator),
        "chip_receipt_sha256": str(chip_receipt_sha256),
        "chip_receipt_locator": str(chip_receipt_locator),
        "evidence_packet_sha256": str(evidence_packet_sha256),
        "evidence_packet_locator": str(evidence_packet_locator),
        "authority_head_record_sha256": str(authority_head_record_sha256),
        "lease_subject_record_sha256": str(lease_subject_record_sha256),
        "lease_execution_record_sha256": str(lease_execution_record_sha256),
        "lease_terminal_record_sha256": str(lease_terminal_record_sha256),
        "finished_at": timestamp,
        "security_boundary_claimed": False,
    }
    body["record_sha256"] = _record_sha256(body)
    existing = load_chip_eda_publication(
        evidence_root,
        source_revision=source_revision,
        execution_id=execution_id,
    )
    if existing is not None:
        if existing != body:
            raise ValueError("chip publication identity is already bound differently")
        return existing
    _publish_evidence_record(evidence_root, "chip-publication", body)
    index_path, identity = _chip_publication_index_path(
        evidence_root,
        source_revision=source_revision,
        execution_id=execution_id,
    )
    index = {
        "schema": CHIP_EDA_PUBLICATION_INDEX_SCHEMA,
        "source_revision": str(source_revision),
        "entrypoint_id": CHIP_EDA_ENTRYPOINT_ID,
        "execution_id": str(execution_id),
        "publication_record_sha256": body["record_sha256"],
        "identity_sha256": identity,
    }
    _publish_exact_bytes_once(
        index_path,
        canonical_json(index).encode("ascii"),
        label="chip publication identity index",
    )
    retained = load_chip_eda_publication(
        evidence_root,
        source_revision=source_revision,
        execution_id=execution_id,
    )
    if retained != body:
        raise ValueError("chip publication identity is already bound differently")
    return retained

__all__ = [
    "record_chip_eda_publication",
    "retain_chip_eda_terminal_artifact",
]
