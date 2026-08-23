"""Additive GateReport-v3 binding the canonical repository-write inventory.

The existing GateReport-v2 import path remains unchanged.  This strangler model
adds mandatory repository-write inventory identity and blocker fields so a
future release verifier cannot infer mutation safety from the entrypoint registry
alone.  It does not issue a release receipt, approval, promotion, or Gate close.

The class name records the strangler generation; ``_SCHEMA`` records the wire
shape.  The shape moved to ``daedalus-gate-report/4`` when the report gained
``repository_write_inventory_schema`` (which inventory schema produced the
evidence) and ``repository_write_scanner_error`` (0 when the scanner produced
evidence, 1 when it refused).  Adding those keys under the old ``/3`` const
would have left one schema id naming two shapes.

The shape moved to ``daedalus-gate-report/5`` when the repository-write
counters stopped being the raw syntactic scan.  Until then
``repository_write_failures`` was every callsite the scanner emitted, so a
registered door, a guard contract, and a lease receipt all subtracted nothing
and the counter could not distinguish an unleased production write from a
callsite nobody had looked at yet.  The report now declares three things
instead of one:

* ``repository_write_surfaces_total`` — the raw syntactic surface count, kept
  verbatim so the classification can never hide a callsite;
* ``repository_write_surface_verdicts`` — one verdict per surface, from the
  classification chain's own vocabulary, as sorted ``<verdict>:<count>`` rows
  that sum to the total;
* ``repository_write_classification_schema`` — which chain wire produced those
  verdicts, read back out of the projection rather than asserted.

``repository_write_failures`` is now the surfaces the chain leaves as genuine
blockers.  Clearing a surface never empties the counter silently: every
cleared surface whose evidence the six verifiers did not authenticate, per
surface, is counted back into a ``classification:`` row.  The report cannot be
closed by a declaration alone.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from daedalus.schemas import RuntimeConformanceReceipt
from daedalus.spine.envelope import canonical_json

from .report import GateReport, build_gate0_report
from .repository_write_classification import (
    CLASSIFICATION_SCHEMA,
    NON_BLOCKING_SURFACE_VERDICT,
    STAGE_VERDICT_NOT_APPLICABLE,
    STAGE_VERDICT_VERIFIED,
    UNCLASSIFIED_SURFACE_VERDICT,
    RepositoryWriteClassificationError,
    authenticate_repository_write_surfaces,
    project_classification_input,
    project_repository_write_classifications,
    surface_classification_verdict,
)
from .repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteInventoryV2Error,
    scan_repository_write_surfaces_v2,
)


_SCHEMA = "daedalus-gate-report/5"
# The exact repository-write inventory schema this reporter is written
# against.  The report declares the schema it observed; a mismatch is a
# blocker, never a silent acceptance.  Moving the scanner record shape
# (GATE0_V3_SCANNER_IDENTITY_DECISION.md option A) moves this const with it.
_INVENTORY_SCHEMA = "daedalus-gate0-repository-write-inventory/2"
# The exact classification-chain wire this reporter is written against.  Same
# discipline as the inventory schema: the value in the report is read back out
# of the projection the chain produced, and disagreement with this const is a
# blocker.
_CLASSIFICATION_SCHEMA = CLASSIFICATION_SCHEMA
_MAX_CLASSIFICATION_BYTES = 16 * 1024 * 1024
_MAX_REPORT_BYTES = 4 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_V2_SHARED_FIELDS = {
    "gate",
    "source_revision",
    "registry_sha256",
    "security_boundary_claimed",
    "unregistered_effectful_entrypoints",
    "unguarded_entrypoints",
    "inventory_only_production_entrypoints",
    "missing_guard_contracts",
    "runtime_conformance_failures",
    "fault_injection_failures",
    "primary_checkout_mutations",
    "event_store_writer_inventory_sha256",
    "event_store_writer_failures",
    "owner_approval_enforced",
    "diagnostics",
}
_V3_FIELDS = frozenset(
    {
        "schema",
        "closed",
        "blockers",
        "report_sha256",
        "repository_write_inventory_sha256",
        "repository_write_scan_input_sha256",
        "repository_write_files_scanned",
        "repository_write_inventory_generation",
        "repository_write_inventory_schema",
        "repository_write_scanner_error",
        "repository_write_surfaces_total",
        "repository_write_classification_schema",
        "repository_write_surface_verdicts",
        "repository_write_failures",
        *_V2_SHARED_FIELDS,
    }
)
# ``<verdict>:<count>`` where the verdict is one of the chain's own values.
_VERDICT_ROW = re.compile(r"^[a-z_]+(?::[a-z_+-]+)*:(0|[1-9][0-9]*)$")


class GateReportV3Error(ValueError):
    """GateReport-v3 input is malformed or non-canonical."""


def _sha256_or_none(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise GateReportV3Error(f"{label} must be lowercase sha256 or null")
    return value


def _bounded_string_or_none(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 4000:
        raise GateReportV3Error(f"{label} must be a bounded string or null")
    return value


def _strict_bool(payload: Mapping[str, Any], name: str) -> bool:
    value = payload.get(name)
    if type(value) is not bool:
        raise GateReportV3Error(f"{name} must be a boolean")
    return value


def _strict_int(payload: Mapping[str, Any], name: str) -> int:
    value = payload.get(name)
    if type(value) is not int:
        raise GateReportV3Error(f"{name} must be an integer")
    return value


def _strict_string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value or len(value) > 4000:
        raise GateReportV3Error(f"{name} must be a bounded non-empty string")
    return value


def _strict_rows(payload: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = payload.get(name)
    if not isinstance(value, list):
        raise GateReportV3Error(f"{name} must be an array")
    if any(not isinstance(row, str) or not row or len(row) > 4000 for row in value):
        raise GateReportV3Error(f"{name} must contain bounded strings")
    if value != sorted(set(value)):
        raise GateReportV3Error(f"{name} must be sorted and unique")
    return tuple(value)


def _normalize_rows(values: Iterable[str], label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise GateReportV3Error(f"{label} must be a sequence of strings")
    try:
        rows = tuple(values)
    except TypeError as exc:
        raise GateReportV3Error(
            f"{label} must be a sequence of strings"
        ) from exc
    if any(not isinstance(row, str) or not row or len(row) > 4000 for row in rows):
        raise GateReportV3Error(f"{label} contains an invalid row")
    return tuple(sorted(set(rows)))


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GateReportV3Error(f"duplicate GateReport-v3 key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise GateReportV3Error(f"non-finite GateReport-v3 constant: {value}")


@dataclass(frozen=True)
class GateReportV3(GateReport):
    """GateReport-v2 plus exact canonical repository-write inventory evidence."""

    repository_write_inventory_sha256: str | None = None
    repository_write_scan_input_sha256: str | None = None
    repository_write_files_scanned: int = 0
    repository_write_inventory_generation: int = 0
    repository_write_inventory_schema: str | None = None
    repository_write_scanner_error: int = 0
    repository_write_surfaces_total: int = 0
    repository_write_classification_schema: str | None = None
    repository_write_surface_verdicts: tuple[str, ...] = ()
    repository_write_failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(
            self,
            "repository_write_inventory_sha256",
            _sha256_or_none(
                self.repository_write_inventory_sha256,
                "repository_write_inventory_sha256",
            ),
        )
        object.__setattr__(
            self,
            "repository_write_scan_input_sha256",
            _sha256_or_none(
                self.repository_write_scan_input_sha256,
                "repository_write_scan_input_sha256",
            ),
        )
        if (
            type(self.repository_write_files_scanned) is not int
            or self.repository_write_files_scanned < 0
        ):
            raise GateReportV3Error(
                "repository_write_files_scanned must be a non-negative integer"
            )
        if (
            type(self.repository_write_inventory_generation) is not int
            or self.repository_write_inventory_generation < 0
        ):
            raise GateReportV3Error(
                "repository_write_inventory_generation must be a non-negative integer"
            )
        if self.repository_write_inventory_schema is not None and (
            not isinstance(self.repository_write_inventory_schema, str)
            or not self.repository_write_inventory_schema
            or len(self.repository_write_inventory_schema) > 4000
        ):
            raise GateReportV3Error(
                "repository_write_inventory_schema must be a bounded string or null"
            )
        if (
            type(self.repository_write_scanner_error) is not int
            or self.repository_write_scanner_error < 0
        ):
            raise GateReportV3Error(
                "repository_write_scanner_error must be a non-negative integer"
            )
        if (
            type(self.repository_write_surfaces_total) is not int
            or self.repository_write_surfaces_total < 0
        ):
            raise GateReportV3Error(
                "repository_write_surfaces_total must be a non-negative integer"
            )
        if self.repository_write_classification_schema is not None and (
            not isinstance(self.repository_write_classification_schema, str)
            or not self.repository_write_classification_schema
            or len(self.repository_write_classification_schema) > 4000
        ):
            raise GateReportV3Error(
                "repository_write_classification_schema must be a bounded string"
                " or null"
            )
        object.__setattr__(
            self,
            "repository_write_surface_verdicts",
            _normalize_rows(
                self.repository_write_surface_verdicts,
                "repository_write_surface_verdicts",
            ),
        )
        object.__setattr__(
            self,
            "repository_write_failures",
            _normalize_rows(
                self.repository_write_failures,
                "repository_write_failures",
            ),
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        base_property = GateReport.blockers.fget
        if base_property is None:  # pragma: no cover - property contract invariant
            raise GateReportV3Error("GateReport blockers property is unavailable")
        rows = list(base_property(self))
        if self.repository_write_inventory_sha256 is None:
            rows.append("repository_write_inventory_sha256:missing")
        if self.repository_write_scan_input_sha256 is None:
            rows.append("repository_write_scan_input_sha256:missing")
        if self.repository_write_files_scanned < 1:
            rows.append("repository_write_files_scanned:missing")
        if self.repository_write_inventory_generation != 2:
            rows.append(
                "repository_write_inventory_generation:unsupported:"
                f"{self.repository_write_inventory_generation}"
            )
        if self.repository_write_scanner_error != 0:
            rows.append(
                "repository_write_scanner_error:"
                f"{self.repository_write_scanner_error}"
            )
        if self.repository_write_inventory_schema != _INVENTORY_SCHEMA:
            rows.append(
                "repository_write_inventory_schema:unsupported:"
                f"{self.repository_write_inventory_schema}"
            )
        # Which chain classified the surfaces.  A report whose counters were
        # never classified declares null here and is blocked for it, so the
        # raw syntactic scan cannot be presented as a classified census.
        if self.repository_write_classification_schema != _CLASSIFICATION_SCHEMA:
            rows.append(
                "repository_write_classification_schema:unsupported:"
                f"{self.repository_write_classification_schema}"
            )
        # The census must account for every syntactic surface.  A malformed or
        # short census is a blocker, never a quietly smaller denominator.
        counted = 0
        for row in self.repository_write_surface_verdicts:
            if not _VERDICT_ROW.fullmatch(row):
                rows.append(f"repository_write_surface_verdicts:malformed:{row}")
                counted = -1
                break
            counted += int(row.rsplit(":", 1)[1])
        if counted != self.repository_write_surfaces_total:
            rows.append(
                "repository_write_surface_verdicts:inconsistent:"
                f"{counted}:{self.repository_write_surfaces_total}"
            )
        rows.extend(
            f"repository_write_failures:{row}"
            for row in self.repository_write_failures
        )
        return tuple(sorted(set(rows)))

    @property
    def closed(self) -> bool:
        return bool(
            self.security_boundary_claimed
            and self.owner_approval_enforced
            and not self.blockers
        )

    def _body_v3(self) -> dict[str, Any]:
        body = GateReport._body_v2(self)
        body["schema"] = _SCHEMA
        body["repository_write_inventory_sha256"] = (
            self.repository_write_inventory_sha256
        )
        body["repository_write_scan_input_sha256"] = (
            self.repository_write_scan_input_sha256
        )
        body["repository_write_files_scanned"] = (
            self.repository_write_files_scanned
        )
        body["repository_write_inventory_generation"] = (
            self.repository_write_inventory_generation
        )
        body["repository_write_inventory_schema"] = (
            self.repository_write_inventory_schema
        )
        body["repository_write_scanner_error"] = (
            self.repository_write_scanner_error
        )
        body["repository_write_surfaces_total"] = (
            self.repository_write_surfaces_total
        )
        body["repository_write_classification_schema"] = (
            self.repository_write_classification_schema
        )
        body["repository_write_surface_verdicts"] = list(
            self.repository_write_surface_verdicts
        )
        body["repository_write_failures"] = list(
            self.repository_write_failures
        )
        body["closed"] = self.closed
        body["blockers"] = list(self.blockers)
        return body

    def to_dict(self) -> dict[str, Any]:
        body = self._body_v3()
        body["report_sha256"] = hashlib.sha256(
            canonical_json(body).encode("ascii")
        ).hexdigest()
        return body

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GateReportV3":
        if not isinstance(payload, Mapping):
            raise GateReportV3Error("GateReport-v3 root must be an object")
        if set(payload) != _V3_FIELDS:
            raise GateReportV3Error("GateReport-v3 fields are not exact")
        if payload.get("schema") != _SCHEMA:
            raise GateReportV3Error("unsupported GateReport-v3 schema")
        claimed_digest = _sha256_or_none(payload.get("report_sha256"), "report_sha256")
        if claimed_digest is None:
            raise GateReportV3Error("report_sha256 is required")
        digest_body = dict(payload)
        digest_body.pop("report_sha256")
        try:
            actual_digest = hashlib.sha256(
                canonical_json(digest_body).encode("ascii")
            ).hexdigest()
        except (TypeError, ValueError, RecursionError) as exc:
            raise GateReportV3Error(
                "GateReport-v3 payload is not canonical JSON data"
            ) from exc
        if claimed_digest != actual_digest:
            raise GateReportV3Error("GateReport-v3 digest mismatch")

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
        )
        _strict_bool(payload, "closed")
        _strict_rows(payload, "blockers")
        if dict(payload) != report.to_dict():
            raise GateReportV3Error("GateReport-v3 is non-canonical")
        return report


def _read_classification_document(path: Path) -> Mapping[str, Any]:
    """Read one reviewed classification declaration with the loader's strictness."""

    raw = Path(path).read_bytes()
    if len(raw) > _MAX_CLASSIFICATION_BYTES:
        raise GateReportV3Error("classification input exceeds maximum size")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateReportV3Error("classification input must be UTF-8") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, RecursionError) as exc:
        raise GateReportV3Error("classification input is malformed JSON") from exc
    if not isinstance(payload, Mapping) or any(
        not isinstance(key, str) for key in payload
    ):
        raise GateReportV3Error("classification input must be an object")
    return payload


def _surface_failure_row(surface: Any, verdict: str, doors: Sequence[str]) -> str:
    """One failure row: the surface identity, its verdict, and its door if any."""

    row = (
        f"{surface.path}:{surface.line}:{surface.column}:"
        f"{surface.kind}:{surface.callee}:{surface.operation}"
        f":verdict={verdict}"
    )
    if doors:
        row = f"{row}:door={','.join(doors)}"
    return row


def _surface_authentication_failure_row(surface: Any, authentication: Any) -> str:
    """One row per cleared surface whose evidence no verifier authenticated.

    The row names the surface and the stages still owed, so the failure list
    stays a list of callsites rather than a single number.  A stage that does
    not apply to this surface is not owed and is not named.
    """

    pending: list[str] = []
    if authentication is not None:
        pending = sorted(
            name
            for name, verdict in authentication.verdicts
            if verdict
            not in {STAGE_VERDICT_VERIFIED, STAGE_VERDICT_NOT_APPLICABLE}
        )
    return (
        f"classification:surface-unauthenticated:"
        f"{surface.path}:{surface.line}:{surface.column}:"
        f"stages={','.join(pending) if pending else 'none'}"
    )


def _classify_repository_write_surfaces(
    inventory: RepositoryWriteInventoryV2,
    classification_input: Path | None,
) -> tuple[tuple[str, ...], tuple[str, ...], str | None]:
    """Turn the syntactic inventory into a classified census.

    Returns ``(failures, verdict census, declared classification schema)``.
    Every surface the scanner emitted gets exactly one verdict, so the census
    sums to the surface count and no callsite can vanish between the scan and
    the report.  Only the surfaces the classification chain leaves as genuine
    blockers become failures.

    Without a declaration every blocking surface is ``unclassified`` and stays
    a failure — the fail-closed default, and the state of this repository
    today.  With one, the chain decides; and every surface it clears whose
    evidence this call did not authenticate is counted back into a
    ``classification:`` row, so the failure list cannot be emptied by a file.

    Authentication is composed here, in process.  This reporter hands
    ``authenticate_repository_write_surfaces`` nothing but the projection it
    just built: no ``stage_reports`` argument, so no caller-supplied stage
    object can reach the report path at all.  No stage input is wired into
    this reporter yet, so every stage is ``absent``, every surface is
    unauthenticated, and the count below equals the cleared count.  That is
    the honest state, not a placeholder — a surface becomes authenticated when
    a verifier has run over it, never when a document says so, and there is no
    locator here for such a document to arrive through.  Wiring the raw stage
    inputs and running the six verifiers from this call is the next packet.
    """

    document: Mapping[str, Any] | None = None
    input_failures: list[str] = []
    if classification_input is not None:
        try:
            document = _read_classification_document(classification_input)
        except (GateReportV3Error, OSError, TypeError, ValueError):
            document = None
            input_failures.append("classification:input-unreadable")
    try:
        if document is None:
            projection = project_repository_write_classifications(inventory, ())
        else:
            projection = project_classification_input(inventory, document)
    except RepositoryWriteClassificationError:
        # A declaration that does not bind to this exact scan clears nothing.
        input_failures.append("classification:input-refused")
        projection = project_repository_write_classifications(inventory, ())

    payload = projection.to_dict()
    # Observed, not asserted, exactly as with the inventory schema above.
    declared = payload.get("schema")
    classified = {row.surface: row for row in projection.classifications}
    authentications = authenticate_repository_write_surfaces(projection)

    census: dict[str, int] = {}
    failures: list[str] = []
    unauthenticated_rows: list[str] = []
    cleared = 0
    authenticated_cleared = 0
    for surface in inventory.surfaces:
        if not surface.blocking:
            # The scanner already proved this callsite cannot write; it was
            # never a failure and classification does not make it one.
            census[NON_BLOCKING_SURFACE_VERDICT] = (
                census.get(NON_BLOCKING_SURFACE_VERDICT, 0) + 1
            )
            continue
        row = classified.get(surface)
        if row is None:
            verdict = UNCLASSIFIED_SURFACE_VERDICT
            failures.append(_surface_failure_row(surface, verdict, ()))
        else:
            verdict = surface_classification_verdict(row)
            if row.candidate_blockers:
                failures.append(
                    _surface_failure_row(surface, verdict, row.guard_contracts)
                )
            else:
                cleared += 1
                authentication = authentications.get(surface)
                if authentication is not None and authentication.authenticated:
                    authenticated_cleared += 1
                else:
                    unauthenticated_rows.append(
                        _surface_authentication_failure_row(surface, authentication)
                    )
        census[verdict] = census.get(verdict, 0) + 1

    # Per surface, not per report.  The old row read one module-wide boolean
    # off the classification payload and fired for every cleared surface at
    # once; under any scope cap that flag was false for reasons having nothing
    # to do with the surfaces in scope.  What is counted here is the surfaces
    # this call cleared but could not authenticate — nothing more.
    unauth = cleared - authenticated_cleared
    if unauth:
        failures.append(f"classification:evidence-unauthenticated:{unauth}")
        # The count is still an aggregate, so it never travels alone: one row
        # per surface names the callsite and the stages it still owes.
        failures.extend(unauthenticated_rows)
    if cleared:
        # The classification layer is still not bound to a GateReport, so a
        # declaration replaces N named surfaces with one row saying so, and
        # closure stays impossible until that binding exists.
        if payload.get("gate_report_bound") is not True:
            failures.append("classification:gate-report-binding-missing")
    failures.extend(input_failures)
    verdicts = tuple(f"{name}:{count}" for name, count in census.items())
    return (
        tuple(sorted(set(failures))),
        verdicts,
        declared if isinstance(declared, str) and declared else None,
    )


def _repository_write_evidence(
    root: Path,
    *,
    source_revision: str,
    classification_input: Path | None = None,
) -> tuple[
    str | None,
    str | None,
    int,
    int,
    tuple[str, ...],
    tuple[str, ...],
    str | None,
    int,
    int,
    str | None,
    tuple[str, ...],
]:
    try:
        inventory = scan_repository_write_surfaces_v2(
            root,
            source_revision=source_revision,
        )
    except RepositoryWriteInventoryV2Error:
        return (
            None,
            None,
            0,
            0,
            ("inventory-refused",),
            ("blocker:repository_write_inventory:refused",),
            None,
            1,
            0,
            None,
            (),
        )
    # The raw syntactic scan stays visible: ``surfaces`` is every callsite the
    # scanner emitted and ``inventory.blockers`` its blocking subset, which is
    # what this report used to publish verbatim as its failures.
    surfaces_total = len(inventory.surfaces)
    syntactic_blockers = len(inventory.blockers)
    failures, verdicts, classification_schema = _classify_repository_write_surfaces(
        inventory,
        classification_input,
    )
    # Observed, not asserted: the schema string is read back out of the
    # artifact the scanner produced, so a scanner schema change shows up in
    # the report as a mismatch blocker instead of passing silently.
    declared = inventory.to_dict().get("schema")
    return (
        inventory.digest,
        inventory.scan_input_sha256,
        inventory.files_scanned,
        2,
        failures,
        (f"repository_write_syntactic_blockers:{syntactic_blockers}",),
        declared if isinstance(declared, str) and declared else None,
        0,
        surfaces_total,
        classification_schema,
        verdicts,
    )


def _build_base_report(
    root: Path,
    *,
    source_revision: str,
    runtime_receipts: tuple[RuntimeConformanceReceipt, ...],
    fault_results: Mapping[str, bool] | None,
    primary_checkout_mutations: tuple[str, ...],
    security_boundary_claimed: bool,
    fault_matrix_evidence_dir: Path | None = None,
    runtime_conformance_receipt_dir: Path | None = None,
) -> GateReport:
    report = build_gate0_report(
        root,
        source_revision=source_revision,
        runtime_receipts=runtime_receipts,
        fault_results=fault_results,
        primary_checkout_mutations=primary_checkout_mutations,
        security_boundary_claimed=security_boundary_claimed,
        fault_matrix_evidence_dir=fault_matrix_evidence_dir,
        runtime_conformance_receipt_dir=runtime_conformance_receipt_dir,
    )
    if type(report) is not GateReport:
        raise GateReportV3Error(
            "base GateReport-v2 builder returned a non-exact report"
        )
    return report


def build_gate0_report_v3(
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
) -> GateReportV3:
    """Build v2 and repository-write evidence under a repeated drift fence.

    ``repository_write_classification_input`` names a reviewed classification
    declaration, in the same shape as the other evidence directories: the
    caller supplies a locator, never a verdict.  The declaration is bound to
    the exact revision and inventory digest of the scan performed here, so a
    stale or foreign document clears nothing.  Omitting it leaves every
    blocking surface unclassified, which is the fail-closed default.
    """

    root = repo_root.resolve()
    classification_input = (
        None
        if repository_write_classification_input is None
        else Path(repository_write_classification_input)
    )
    receipt_rows = tuple(runtime_receipts)
    mutation_rows = tuple(primary_checkout_mutations)
    fault_rows = None if fault_results is None else dict(fault_results)

    base_before = _build_base_report(
        root,
        source_revision=source_revision,
        runtime_receipts=receipt_rows,
        fault_results=fault_rows,
        primary_checkout_mutations=mutation_rows,
        security_boundary_claimed=security_boundary_claimed,
        fault_matrix_evidence_dir=fault_matrix_evidence_dir,
        runtime_conformance_receipt_dir=runtime_conformance_receipt_dir,
    )
    inventory_before = _repository_write_evidence(
        root,
        source_revision=source_revision,
        classification_input=classification_input,
    )
    base_after = _build_base_report(
        root,
        source_revision=source_revision,
        runtime_receipts=receipt_rows,
        fault_results=fault_rows,
        primary_checkout_mutations=mutation_rows,
        security_boundary_claimed=security_boundary_claimed,
        fault_matrix_evidence_dir=fault_matrix_evidence_dir,
        runtime_conformance_receipt_dir=runtime_conformance_receipt_dir,
    )
    inventory_after = _repository_write_evidence(
        root,
        source_revision=source_revision,
        classification_input=classification_input,
    )
    if base_before.to_dict() != base_after.to_dict():
        raise GateReportV3Error(
            "base GateReport-v2 changed while composing GateReport-v3"
        )
    if inventory_before != inventory_after:
        raise GateReportV3Error(
            "repository-write inventory changed while composing GateReport-v3"
        )

    (
        inventory_digest,
        scan_input_digest,
        files_scanned,
        generation,
        failures,
        diagnostics,
        inventory_schema,
        scanner_error,
        surfaces_total,
        classification_schema,
        verdicts,
    ) = inventory_after
    base_fields = {
        field.name: getattr(base_after, field.name)
        for field in dataclasses.fields(GateReport)
    }
    base_fields["diagnostics"] = tuple(
        sorted(set(base_after.diagnostics).union(diagnostics))
    )
    return GateReportV3(
        **base_fields,
        repository_write_inventory_sha256=inventory_digest,
        repository_write_scan_input_sha256=scan_input_digest,
        repository_write_files_scanned=files_scanned,
        repository_write_inventory_generation=generation,
        repository_write_inventory_schema=inventory_schema,
        repository_write_scanner_error=scanner_error,
        repository_write_surfaces_total=surfaces_total,
        repository_write_classification_schema=classification_schema,
        repository_write_surface_verdicts=verdicts,
        repository_write_failures=failures,
    )


def load_gate_report_v3(path: str | Path) -> GateReportV3:
    try:
        raw = Path(path).read_bytes()
    except (OSError, TypeError) as exc:
        raise GateReportV3Error("GateReport-v3 could not be read") from exc
    if len(raw) > _MAX_REPORT_BYTES:
        raise GateReportV3Error("GateReport-v3 exceeds maximum size")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateReportV3Error("GateReport-v3 must be UTF-8") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, RecursionError) as exc:
        raise GateReportV3Error("GateReport-v3 is malformed JSON") from exc
    return GateReportV3.from_dict(payload)


def assert_monotonic_v3(
    current: GateReportV3,
    baseline: GateReportV3,
) -> tuple[str, ...]:
    if type(current) is not GateReportV3 or type(baseline) is not GateReportV3:
        raise GateReportV3Error("monotonic comparison requires exact GateReportV3")
    if current.gate != baseline.gate:
        raise GateReportV3Error("cannot compare different gates")
    return tuple(sorted(set(current.blockers) - set(baseline.blockers)))


__all__ = [
    "GateReportV3",
    "GateReportV3Error",
    "assert_monotonic_v3",
    "build_gate0_report_v3",
    "load_gate_report_v3",
]
