"""GateReport-v4: exact binding to a retained repository-write verifier chain.

This additive strangler consumes GateReport-v3, an exact classification
projection, and the canonical chain-result artifact.  It removes the reporter's
placeholder unauthenticated rows only after every revision, inventory,
classification, surface, applicability, blocker and digest binding agrees.

The report remains evidence, not release authority.  It issues no approval,
release receipt, promotion receipt, merge, promotion, or Gate transition.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from daedalus.schemas import RuntimeConformanceReceipt
from daedalus.spine.envelope import canonical_json

from .report_v3 import (
    GateReportV3,
    GateReportV3Error,
    _MAX_REPORT_BYTES,
    _V3_FIELDS,
    _bounded_string_or_none,
    _read_classification_document,
    _reject_duplicate_keys,
    _reject_json_constant,
    _sha256_or_none,
    _strict_bool,
    _strict_int,
    _strict_rows,
    _strict_string,
    build_gate0_report_v3,
)
from .repository_write_chain_result import (
    CHAIN_RESULT_SCHEMA,
    RepositoryWriteChainResult,
    RepositoryWriteChainResultError,
    RepositoryWriteChainSurface,
    load_repository_write_chain_result,
)
from .repository_write_classification import (
    CLASSIFICATION_SCHEMA,
    STAGE_VERDICT_NOT_APPLICABLE,
    STAGE_VERDICT_VERIFIED,
    RepositoryWriteClassificationError,
    RepositoryWriteClassificationReport,
    applicable_authentication_stages,
    project_classification_input,
    project_repository_write_classifications,
    surface_binding_sha256,
    surface_classification_verdict,
)
from .repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteInventoryV2Error,
    RepositoryWriteSurface,
    scan_repository_write_surfaces_v2,
)


_SCHEMA = "daedalus-gate-report/6"
_V4_FIELDS = frozenset(
    set(_V3_FIELDS)
    | {
        "repository_write_chain_result_schema",
        "repository_write_chain_result_sha256",
    }
)


class GateReportV4Error(GateReportV3Error):
    """GateReport-v4 or its retained chain binding is invalid."""


@dataclass(frozen=True)
class GateReportV4(GateReportV3):
    """GateReport-v3 plus one exact retained verifier-chain identity."""

    repository_write_chain_result_schema: str | None = None
    repository_write_chain_result_sha256: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(
            self,
            "repository_write_chain_result_schema",
            _bounded_string_or_none(
                self.repository_write_chain_result_schema,
                "repository_write_chain_result_schema",
            ),
        )
        object.__setattr__(
            self,
            "repository_write_chain_result_sha256",
            _sha256_or_none(
                self.repository_write_chain_result_sha256,
                "repository_write_chain_result_sha256",
            ),
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        base_property = GateReportV3.blockers.fget
        if base_property is None:  # pragma: no cover - property invariant
            raise GateReportV4Error("GateReport-v3 blockers property is unavailable")
        rows = list(base_property(self))
        if self.repository_write_chain_result_schema != CHAIN_RESULT_SCHEMA:
            rows.append(
                "repository_write_chain_result_schema:unsupported:"
                f"{self.repository_write_chain_result_schema}"
            )
        if self.repository_write_chain_result_sha256 is None:
            rows.append("repository_write_chain_result_sha256:missing")
        return tuple(sorted(set(rows)))

    def _body_v4(self) -> dict[str, Any]:
        body = GateReportV3._body_v3(self)
        body["schema"] = _SCHEMA
        body["repository_write_chain_result_schema"] = (
            self.repository_write_chain_result_schema
        )
        body["repository_write_chain_result_sha256"] = (
            self.repository_write_chain_result_sha256
        )
        body["closed"] = self.closed
        body["blockers"] = list(self.blockers)
        return body

    def to_dict(self) -> dict[str, Any]:
        body = self._body_v4()
        body["report_sha256"] = hashlib.sha256(
            canonical_json(body).encode("ascii")
        ).hexdigest()
        return body

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GateReportV4":
        if not isinstance(payload, Mapping):
            raise GateReportV4Error("GateReport-v4 root must be an object")
        if set(payload) != _V4_FIELDS:
            raise GateReportV4Error("GateReport-v4 fields are not exact")
        if payload.get("schema") != _SCHEMA:
            raise GateReportV4Error("unsupported GateReport-v4 schema")
        claimed_digest = _sha256_or_none(
            payload.get("report_sha256"), "report_sha256"
        )
        if claimed_digest is None:
            raise GateReportV4Error("report_sha256 is required")
        digest_body = dict(payload)
        digest_body.pop("report_sha256")
        try:
            actual_digest = hashlib.sha256(
                canonical_json(digest_body).encode("ascii")
            ).hexdigest()
        except (TypeError, ValueError, RecursionError) as exc:
            raise GateReportV4Error(
                "GateReport-v4 payload is not canonical JSON data"
            ) from exc
        if claimed_digest != actual_digest:
            raise GateReportV4Error("GateReport-v4 digest mismatch")

        report = cls(
            gate=_strict_int(payload, "gate"),
            source_revision=_strict_string(payload, "source_revision"),
            registry_sha256=_strict_string(payload, "registry_sha256"),
            security_boundary_claimed=_strict_bool(
                payload, "security_boundary_claimed"
            ),
            unregistered_effectful_entrypoints=_strict_rows(
                payload, "unregistered_effectful_entrypoints"
            ),
            unguarded_entrypoints=_strict_rows(
                payload, "unguarded_entrypoints"
            ),
            inventory_only_production_entrypoints=_strict_rows(
                payload, "inventory_only_production_entrypoints"
            ),
            missing_guard_contracts=_strict_rows(
                payload, "missing_guard_contracts"
            ),
            runtime_conformance_failures=_strict_rows(
                payload, "runtime_conformance_failures"
            ),
            fault_injection_failures=_strict_rows(
                payload, "fault_injection_failures"
            ),
            primary_checkout_mutations=_strict_rows(
                payload, "primary_checkout_mutations"
            ),
            event_store_writer_inventory_sha256=_sha256_or_none(
                payload.get("event_store_writer_inventory_sha256"),
                "event_store_writer_inventory_sha256",
            ),
            event_store_writer_failures=_strict_rows(
                payload, "event_store_writer_failures"
            ),
            owner_approval_enforced=_strict_bool(
                payload, "owner_approval_enforced"
            ),
            diagnostics=_strict_rows(payload, "diagnostics"),
            repository_write_inventory_sha256=_sha256_or_none(
                payload.get("repository_write_inventory_sha256"),
                "repository_write_inventory_sha256",
            ),
            repository_write_scan_input_sha256=_sha256_or_none(
                payload.get("repository_write_scan_input_sha256"),
                "repository_write_scan_input_sha256",
            ),
            repository_write_files_scanned=_strict_int(
                payload, "repository_write_files_scanned"
            ),
            repository_write_inventory_generation=_strict_int(
                payload, "repository_write_inventory_generation"
            ),
            repository_write_inventory_schema=_bounded_string_or_none(
                payload.get("repository_write_inventory_schema"),
                "repository_write_inventory_schema",
            ),
            repository_write_scanner_error=_strict_int(
                payload, "repository_write_scanner_error"
            ),
            repository_write_surfaces_total=_strict_int(
                payload, "repository_write_surfaces_total"
            ),
            repository_write_classification_schema=_bounded_string_or_none(
                payload.get("repository_write_classification_schema"),
                "repository_write_classification_schema",
            ),
            repository_write_surface_verdicts=_strict_rows(
                payload, "repository_write_surface_verdicts"
            ),
            repository_write_failures=_strict_rows(
                payload, "repository_write_failures"
            ),
            repository_write_chain_result_schema=_bounded_string_or_none(
                payload.get("repository_write_chain_result_schema"),
                "repository_write_chain_result_schema",
            ),
            repository_write_chain_result_sha256=_sha256_or_none(
                payload.get("repository_write_chain_result_sha256"),
                "repository_write_chain_result_sha256",
            ),
        )
        _strict_bool(payload, "closed")
        _strict_rows(payload, "blockers")
        if dict(payload) != report.to_dict():
            raise GateReportV4Error("GateReport-v4 is non-canonical")
        return report


@dataclass(frozen=True)
class _ChainBindingSnapshot:
    schema: str | None
    digest: str | None
    inventory_digest: str | None
    classification_digest: str | None
    authentication_failures: tuple[str, ...]
    refusal: str | None = None

    @property
    def bound(self) -> bool:
        return (
            self.refusal is None
            and self.schema == CHAIN_RESULT_SCHEMA
            and self.digest is not None
            and self.inventory_digest is not None
            and self.classification_digest is not None
        )


def verify_repository_write_chain_result_binding(
    inventory: RepositoryWriteInventoryV2,
    projection: RepositoryWriteClassificationReport,
    chain_result: RepositoryWriteChainResult,
) -> Mapping[RepositoryWriteSurface, RepositoryWriteChainSurface]:
    """Verify one retained chain against the exact inventory and projection.

    A digest match alone is insufficient.  Applicability and blockers are
    re-derived from the typed classification rows, and every retained surface
    must match the full identity available at this layer.
    """

    if type(inventory) is not RepositoryWriteInventoryV2:
        raise GateReportV4Error("chain binding inventory must be exact inventory-v2")
    if type(projection) is not RepositoryWriteClassificationReport:
        raise GateReportV4Error(
            "chain binding classification must be exact classification report"
        )
    if type(chain_result) is not RepositoryWriteChainResult:
        raise GateReportV4Error("chain binding result must be exact chain result")
    if projection.source_revision != inventory.source_revision:
        raise GateReportV4Error("classification and inventory revisions differ")
    if projection.inventory_digest != inventory.digest:
        raise GateReportV4Error("classification and inventory digests differ")
    if chain_result.source_revision != projection.source_revision:
        raise GateReportV4Error("chain result names another source revision")
    if chain_result.inventory_digest != inventory.digest:
        raise GateReportV4Error("chain result names another inventory")
    if chain_result.classification_digest != projection.digest:
        raise GateReportV4Error("chain result names another classification")
    if chain_result.classification_schema != CLASSIFICATION_SCHEMA:
        raise GateReportV4Error("chain result classification schema is unsupported")
    if chain_result.inventory_surface_count != projection.inventory_surface_count:
        raise GateReportV4Error("chain result inventory count is detached")
    if chain_result.missing_surface_count != len(projection.missing_surfaces):
        raise GateReportV4Error("chain result missing-surface count is detached")
    if len(chain_result.surfaces) != len(projection.classifications):
        raise GateReportV4Error("chain result classified-surface count is detached")

    retained = {row.surface_sha256: row for row in chain_result.surfaces}
    if len(retained) != len(chain_result.surfaces):
        raise GateReportV4Error("chain result surface bindings are ambiguous")
    bound: dict[RepositoryWriteSurface, RepositoryWriteChainSurface] = {}
    for row in projection.classifications:
        digest = surface_binding_sha256(row.source_revision, row.surface)
        record = retained.get(digest)
        if record is None:
            raise GateReportV4Error("classified surface is absent from chain result")
        if (
            record.path,
            record.line,
            record.column,
            record.origin,
        ) != (
            row.surface.path,
            row.surface.line,
            row.surface.column,
            row.surface.origin,
        ):
            raise GateReportV4Error("chain result surface identity is detached")
        if record.classification_verdict != surface_classification_verdict(row):
            raise GateReportV4Error("chain result classification verdict is detached")
        if record.candidate_blockers != tuple(sorted(set(row.candidate_blockers))):
            raise GateReportV4Error("chain result candidate blockers are detached")
        expected_applicable = tuple(
            sorted(stage.value for stage in applicable_authentication_stages(row))
        )
        if record.applicable != expected_applicable:
            raise GateReportV4Error("chain result stage applicability is detached")
        expected_binding = (
            ""
            if row.non_runtime_conformity is None
            else row.non_runtime_conformity.execution_id
        )
        if record.not_applicable_binding != expected_binding:
            raise GateReportV4Error(
                "chain result non-runtime applicability binding is detached"
            )
        bound[row.surface] = record
    if set(retained) != {
        surface_binding_sha256(row.source_revision, row.surface)
        for row in projection.classifications
    }:
        raise GateReportV4Error("chain result contains a foreign surface")
    return bound


def _authentication_failure_row(
    surface: RepositoryWriteSurface,
    record: RepositoryWriteChainSurface,
) -> str:
    pending = sorted(
        name
        for name, verdict in record.stages
        if verdict not in {STAGE_VERDICT_VERIFIED, STAGE_VERDICT_NOT_APPLICABLE}
    )
    return (
        "classification:surface-unauthenticated:"
        f"{surface.path}:{surface.line}:{surface.column}:"
        f"stages={','.join(pending) if pending else 'none'}"
    )


def _actual_authentication_failures(
    projection: RepositoryWriteClassificationReport,
    bound: Mapping[RepositoryWriteSurface, RepositoryWriteChainSurface],
) -> tuple[str, ...]:
    rows: list[str] = []
    for classification in projection.classifications:
        if classification.candidate_blockers:
            continue
        record = bound[classification.surface]
        if not record.authenticated:
            rows.append(_authentication_failure_row(classification.surface, record))
    if rows:
        rows.append(f"classification:evidence-unauthenticated:{len(rows)}")
    return tuple(sorted(set(rows)))


def _classification_projection(
    root: Path,
    *,
    source_revision: str,
    classification_input: Path | None,
) -> tuple[RepositoryWriteInventoryV2, RepositoryWriteClassificationReport]:
    inventory = scan_repository_write_surfaces_v2(
        root,
        source_revision=source_revision,
    )
    if classification_input is None:
        projection = project_repository_write_classifications(inventory, ())
    else:
        document = _read_classification_document(classification_input)
        projection = project_classification_input(inventory, document)
    return inventory, projection


def _resolve_chain_binding(
    root: Path,
    *,
    source_revision: str,
    classification_input: Path | None,
    chain_result_input: Path | None,
) -> _ChainBindingSnapshot:
    if chain_result_input is None:
        return _ChainBindingSnapshot(None, None, None, None, ())
    try:
        inventory, projection = _classification_projection(
            root,
            source_revision=source_revision,
            classification_input=classification_input,
        )
        chain_result = load_repository_write_chain_result(chain_result_input)
        bound = verify_repository_write_chain_result_binding(
            inventory,
            projection,
            chain_result,
        )
        failures = _actual_authentication_failures(projection, bound)
    except (
        GateReportV3Error,
        GateReportV4Error,
        RepositoryWriteChainResultError,
        RepositoryWriteClassificationError,
        RepositoryWriteInventoryV2Error,
        OSError,
        TypeError,
        ValueError,
    ):
        return _ChainBindingSnapshot(
            None,
            None,
            None,
            None,
            (),
            "classification:chain-result-refused",
        )
    payload = chain_result.to_dict()
    schema = payload.get("schema")
    return _ChainBindingSnapshot(
        schema if isinstance(schema, str) and schema else None,
        chain_result.digest,
        inventory.digest,
        projection.digest,
        failures,
    )


def _bound_failures(
    base_failures: Sequence[str],
    binding: _ChainBindingSnapshot,
) -> tuple[str, ...]:
    if not binding.bound:
        rows = list(base_failures)
        if binding.refusal is not None:
            rows.append(binding.refusal)
        return tuple(sorted(set(rows)))
    rows = [
        row
        for row in base_failures
        if row != "classification:gate-report-binding-missing"
        and not row.startswith("classification:evidence-unauthenticated:")
        and not row.startswith("classification:surface-unauthenticated:")
    ]
    rows.extend(binding.authentication_failures)
    return tuple(sorted(set(rows)))


def build_gate0_report_v4(
    repo_root: Path,
    *,
    source_revision: str,
    runtime_receipts: Sequence[RuntimeConformanceReceipt] = (),
    fault_results: Mapping[str, bool] | None = None,
    primary_checkout_mutations: Iterable[str] = (),
    security_boundary_claimed: bool = False,
    fault_matrix_evidence_dir: Path | None = None,
    runtime_conformance_receipt_dir: Path | None = None,
    repository_write_classification_input: Path | None = None,
    repository_write_chain_result_input: Path | None = None,
) -> GateReportV4:
    """Build GateReport-v4 under repeated report and chain-result drift fences."""

    root = repo_root.resolve()
    classification_input = (
        None
        if repository_write_classification_input is None
        else Path(repository_write_classification_input)
    )
    chain_input = (
        None
        if repository_write_chain_result_input is None
        else Path(repository_write_chain_result_input)
    )
    receipt_rows = tuple(runtime_receipts)
    mutation_rows = tuple(primary_checkout_mutations)
    fault_rows = None if fault_results is None else dict(fault_results)
    kwargs = dict(
        source_revision=source_revision,
        runtime_receipts=receipt_rows,
        fault_results=fault_rows,
        primary_checkout_mutations=mutation_rows,
        security_boundary_claimed=security_boundary_claimed,
        fault_matrix_evidence_dir=fault_matrix_evidence_dir,
        runtime_conformance_receipt_dir=runtime_conformance_receipt_dir,
        repository_write_classification_input=classification_input,
    )

    base_before = build_gate0_report_v3(root, **kwargs)
    binding_before = _resolve_chain_binding(
        root,
        source_revision=source_revision,
        classification_input=classification_input,
        chain_result_input=chain_input,
    )
    base_after = build_gate0_report_v3(root, **kwargs)
    binding_after = _resolve_chain_binding(
        root,
        source_revision=source_revision,
        classification_input=classification_input,
        chain_result_input=chain_input,
    )
    if base_before.to_dict() != base_after.to_dict():
        raise GateReportV4Error(
            "GateReport-v3 changed while composing GateReport-v4"
        )
    if binding_before != binding_after:
        raise GateReportV4Error(
            "repository-write chain result changed while composing GateReport-v4"
        )

    fields = {
        field.name: getattr(base_after, field.name)
        for field in dataclasses.fields(GateReportV3)
    }
    fields["repository_write_failures"] = _bound_failures(
        base_after.repository_write_failures,
        binding_after,
    )
    return GateReportV4(
        **fields,
        repository_write_chain_result_schema=binding_after.schema,
        repository_write_chain_result_sha256=binding_after.digest,
    )


def load_gate_report_v4(path: str | Path) -> GateReportV4:
    try:
        raw = Path(path).read_bytes()
    except (OSError, TypeError) as exc:
        raise GateReportV4Error("GateReport-v4 could not be read") from exc
    if len(raw) > _MAX_REPORT_BYTES:
        raise GateReportV4Error("GateReport-v4 exceeds maximum size")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError as exc:
        raise GateReportV4Error("GateReport-v4 must be UTF-8") from exc
    except (json.JSONDecodeError, RecursionError) as exc:
        raise GateReportV4Error("GateReport-v4 is malformed JSON") from exc
    return GateReportV4.from_dict(payload)


__all__ = [
    "GateReportV4",
    "GateReportV4Error",
    "build_gate0_report_v4",
    "load_gate_report_v4",
    "verify_repository_write_chain_result_binding",
]
