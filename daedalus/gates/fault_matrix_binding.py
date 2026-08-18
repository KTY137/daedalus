"""Bind the whole runtime fault matrix verdict into the Gate-0 report.

The verdict itself is a runtimes-side observation record
(:mod:`daedalus.runtimes.whole_fault_matrix`).  This module holds only the gate
policy over that record: which of its blockers block a Gate-0 exit, which ones an
owner-approved scoping decision has already declared, and — separately — whether
the evidence can carry a security-boundary claim at all.

Three properties are deliberate:

* **Fail-closed.**  A missing, ambiguous, unreadable or self-contradictory bundle
  produces a named blocker.  There is no path from "no evidence" to "no finding".
* **Declaration needs a receipt and a document.**  A ``fault.blocked`` row stops
  blocking only when the run's own receipt names a scoping decision, that
  decision exists in this repository, the receipt is bound to *this* verdict by
  matrix digest, and the receipt's scenario list is exactly the verdict's blocked
  set.  Anything less and every blocked row keeps blocking.
* **Binding is not closure.**  A bound verdict makes the matrix honest and open;
  only a closed verdict signed under production key custody at the report's own
  revision can support ``security_boundary_claimed``.  Development-key runs stay
  marked as such and turn an attempted boundary claim into a blocker.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from daedalus.gates.evidence import FaultMatrixEvidence
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG, RuntimeFaultCatalog
from daedalus.runtimes.whole_fault_matrix import (
    PRODUCTION_KEY_CLASS,
    VERDICT_FILENAME,
    WholeRuntimeFaultMatrixError,
    WholeRuntimeFaultMatrixVerdict,
    discover_whole_matrix_verdicts,
    load_whole_matrix_verdict,
)
from daedalus.schemas import ContractProvenance


RECEIPT_FILENAME = "receipt.json"
RECEIPT_SCHEMA = "daedalus-gate0-whole-matrix-receipt/1"
BLOCKED_CLASS = "fault.blocked"
UNBOUND_PREFIX = "whole-matrix:unbound"
_MAX_RECEIPT_BYTES = 1024 * 1024
_SAFE_TEXT = re.compile(r"[^A-Za-z0-9._:/@=-]+")
_RELATIVE_DOC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")


def _safe(value: object, *, maximum: int = 200) -> str:
    text = _SAFE_TEXT.sub("-", str(value)).strip("-")
    return (text or "unspecified")[:maximum]


@dataclass(frozen=True)
class FaultMatrixBinding:
    """What the gate report may say about the runtime fault matrix, and no more."""

    bound: bool
    attests_closure: bool
    failures: tuple[str, ...]
    diagnostics: tuple[str, ...]
    declared: tuple[str, ...] = ()
    verdict_sha256: str | None = None
    matrix_sha256: str | None = None
    observed_revision: str | None = None
    key_classes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "failures", tuple(sorted(set(self.failures))))
        object.__setattr__(self, "diagnostics", tuple(sorted(set(self.diagnostics))))
        object.__setattr__(self, "declared", tuple(sorted(set(self.declared))))
        if self.attests_closure and (not self.bound or self.failures):
            raise ValueError("a binding with findings cannot attest closure")


def _unbound(reason: str, *, detail: str | None = None) -> FaultMatrixBinding:
    diagnostics = [f"blocker:fault_matrix.unbound:{reason}"]
    if detail is not None:
        diagnostics.append(f"info:fault_matrix.unbound_detail:{_safe(detail)}")
    return FaultMatrixBinding(
        bound=False,
        attests_closure=False,
        failures=(f"{UNBOUND_PREFIX}:{reason}",),
        diagnostics=tuple(diagnostics),
    )


def _read_receipt(path: Path) -> Mapping[str, Any] | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > _MAX_RECEIPT_BYTES:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != RECEIPT_SCHEMA:
        return None
    return payload


def _declaration(
    receipt: Mapping[str, Any] | None,
    verdict: WholeRuntimeFaultMatrixVerdict,
    repo_root: Path,
) -> tuple[tuple[str, ...], tuple[str, ...], str | None]:
    """Return (declared rows, diagnostics, key-class contradiction reason)."""

    # The custody cross-check runs before anything else, so a receipt that claims
    # production key material over a development-key verdict is caught even when
    # the verdict has no blocked row to declare.
    contradiction: str | None = None
    if receipt is not None:
        key_material = receipt.get("key_material")
        if isinstance(key_material, Mapping):
            claimed = key_material.get("class")
            if isinstance(claimed, str) and (claimed,) != verdict.key_classes:
                contradiction = _safe(claimed)

    blocked = tuple(verdict.blockers_by_class.get(BLOCKED_CLASS, ()))
    if not blocked:
        return (), (), contradiction
    if receipt is None:
        return (
            (),
            (
                "info:fault_matrix.declaration_refused:receipt-missing-or-malformed",
            ),
            None,
        )

    matrix = receipt.get("matrix")
    if (
        not isinstance(matrix, Mapping)
        or matrix.get("matrix_sha256") != verdict.matrix_sha256
        or receipt.get("source_revision") != verdict.source_revision
    ):
        return (
            (),
            ("info:fault_matrix.declaration_refused:receipt-not-bound-to-this-verdict",),
            contradiction,
        )

    blockers = receipt.get("blockers")
    if not isinstance(blockers, Mapping):
        return (
            (),
            ("info:fault_matrix.declaration_refused:receipt-has-no-blocker-record",),
            contradiction,
        )
    scoped = blockers.get(BLOCKED_CLASS)
    if not isinstance(scoped, Mapping):
        return (
            (),
            ("info:fault_matrix.declaration_refused:receipt-declares-no-blocked-class",),
            contradiction,
        )
    document = scoped.get("scoped_by")
    if not isinstance(document, str) or not _RELATIVE_DOC.fullmatch(document):
        return (
            (),
            ("info:fault_matrix.declaration_refused:no-scoping-decision-named",),
            contradiction,
        )
    decision = repo_root / document
    if not decision.is_file():
        return (
            (),
            (
                "info:fault_matrix.declaration_refused:scoping-decision-absent:"
                f"{_safe(document)}",
            ),
            contradiction,
        )
    scenarios = scoped.get("scenarios")
    if not isinstance(scenarios, list) or any(
        not isinstance(row, str) or not row for row in scenarios
    ):
        return (
            (),
            ("info:fault_matrix.declaration_refused:scoped-scenarios-malformed",),
            contradiction,
        )
    claimed_rows = tuple(sorted({f"{BLOCKED_CLASS}:{row}" for row in scenarios}))
    if claimed_rows != tuple(sorted(blocked)):
        return (
            (),
            (
                "info:fault_matrix.declaration_refused:"
                "scoped-scenarios-do-not-match-the-verdict",
            ),
            contradiction,
        )
    diagnostics = tuple(
        f"declared:fault_matrix.scoped:{row}@{document}" for row in claimed_rows
    )
    return claimed_rows, diagnostics, contradiction


def bind_fault_matrix_evidence(
    repo_root: str | Path,
    *,
    source_revision: str,
    evidence_dir: str | Path | None = None,
    security_boundary_claimed: bool = False,
) -> FaultMatrixBinding:
    """Bind one whole-matrix verdict, or return a named blocker for why not."""

    root = Path(repo_root).resolve()
    if evidence_dir is None:
        candidates = discover_whole_matrix_verdicts(root)
        if not candidates:
            return _unbound("no-verdict-artifact")
        if len(candidates) > 1:
            # Evidence folders accumulate forever by design, so several
            # discovered verdicts are the normal case, not a defect.  The
            # disambiguation is deterministic: the one verdict observed at the
            # cited revision wins.  Zero matches is not ambiguity -- it is a
            # miss, and the blocker names every considered candidate so the
            # finding stays actionable.  Two or more verdicts claiming the
            # same revision is genuine ambiguity and stays fail-closed.
            matching = []
            for candidate in candidates:
                try:
                    parsed = load_whole_matrix_verdict(candidate)
                except WholeRuntimeFaultMatrixError:
                    continue
                if parsed.source_revision == source_revision:
                    matching.append(candidate)
            if not matching:
                named = ",".join(
                    _safe(candidate.parent.name, maximum=64)
                    for candidate in candidates
                )
                return _unbound(
                    f"no-verdict-at-cited-revision:candidates={named}"
                )
            if len(matching) > 1:
                return _unbound(f"ambiguous-evidence:{len(matching)}")
            verdict_path = matching[0]
        else:
            verdict_path = candidates[0]
    else:
        verdict_path = Path(evidence_dir) / VERDICT_FILENAME
        if not verdict_path.is_file():
            return _unbound("no-verdict-artifact")

    try:
        verdict = load_whole_matrix_verdict(verdict_path)
    except WholeRuntimeFaultMatrixError as exc:
        return _unbound("verdict-invalid", detail=str(exc))

    receipt = _read_receipt(verdict_path.parent / RECEIPT_FILENAME)
    declared, declaration_diagnostics, contradiction = _declaration(receipt, verdict, root)

    failures = [row for row in verdict.blockers if row not in set(declared)]
    diagnostics = [
        f"info:fault_matrix.verdict:{verdict.digest}",
        f"info:fault_matrix.matrix:{verdict.matrix_sha256}",
        f"info:fault_matrix.observed_revision:{_safe(verdict.source_revision)}",
        "info:fault_matrix.trust:signatures-not-reverified-at-report-time",
        *declaration_diagnostics,
    ]
    for column in verdict.columns:
        diagnostics.append(
            f"info:fault_matrix.key_class:{column.authority}={_safe(column.key_class)}"
        )

    if contradiction is not None:
        failures.append(f"whole-matrix:key-class-contradiction:{contradiction}")

    revision_matches = verdict.source_revision == source_revision
    if not revision_matches:
        failures.append(
            f"whole-matrix:observed-at-other-revision:{_safe(verdict.source_revision)}"
        )

    attests_closure = bool(
        verdict.closed
        and verdict.production_key_material
        and revision_matches
        and contradiction is None
        and not failures
    )
    if security_boundary_claimed and not attests_closure:
        if not verdict.production_key_material:
            reason = f"key-material-{_safe(verdict.key_classes[0])}"
        elif not revision_matches:
            reason = "observed-at-other-revision"
        elif declared:
            reason = "scoped-rows-are-declared-not-proven"
        else:
            reason = "open-fault-blockers"
        failures.append(f"whole-matrix:security-boundary-unproven:{reason}")

    return FaultMatrixBinding(
        bound=True,
        attests_closure=attests_closure,
        failures=tuple(failures),
        diagnostics=tuple(diagnostics),
        declared=declared,
        verdict_sha256=verdict.digest,
        matrix_sha256=verdict.matrix_sha256,
        observed_revision=verdict.source_revision,
        key_classes=verdict.key_classes,
    )


def fault_matrix_evidence_from_verdict(
    verdict: WholeRuntimeFaultMatrixVerdict,
    *,
    matrix_id: str,
    executed_at: str,
    catalog: RuntimeFaultCatalog = RUNTIME_FAULT_CATALOG,
) -> FaultMatrixEvidence:
    """Bridge the whole-matrix verdict into the existing release-path evidence row.

    The row's ``matrix_sha256`` is the digest from the verdict contract, so the
    strict verifier's ``trusted_fault_matrix_sha256s`` check binds exactly the
    matrix the verdict observed.  ``status`` claims ``passed`` only for a closed
    verdict signed under production key custody; a development-key verdict is
    retained but marked as such in its provenance origin and mapped to
    ``failed``, so it can never carry a closure claim through the release path.
    """
    if not isinstance(verdict, WholeRuntimeFaultMatrixVerdict):
        raise ValueError("fault-matrix bridging requires an exact whole-matrix verdict")
    if not isinstance(catalog, RuntimeFaultCatalog):
        raise ValueError("fault-matrix bridging requires an exact runtime fault catalog")
    if catalog.digest != verdict.catalog_sha256:
        raise ValueError(
            "verdict catalog digest does not match the supplied catalog: "
            f"verdict={verdict.catalog_sha256} catalog={catalog.digest}"
        )
    production = verdict.production_key_material
    key_class_mark = (
        PRODUCTION_KEY_CLASS if production else "-".join(sorted(verdict.key_classes))
    )
    return FaultMatrixEvidence(
        matrix_id=matrix_id,
        source_revision=verdict.source_revision,
        status="passed" if (verdict.closed and production) else "failed",
        matrix_sha256=verdict.matrix_sha256,
        scenario_ids=tuple(row.scenario_id for row in catalog.scenarios),
        executed_at=executed_at,
        provenance=ContractProvenance(
            origin=f"runtimes.whole-fault-matrix.{_safe(key_class_mark)}",
            source_revision=verdict.source_revision,
            created_at=executed_at,
            input_digests=tuple(
                sorted({verdict.matrix_sha256, verdict.catalog_sha256, verdict.digest})
            ),
        ),
    )


__all__ = [
    "BLOCKED_CLASS",
    "FaultMatrixBinding",
    "PRODUCTION_KEY_CLASS",
    "RECEIPT_FILENAME",
    "RECEIPT_SCHEMA",
    "UNBOUND_PREFIX",
    "bind_fault_matrix_evidence",
    "fault_matrix_evidence_from_verdict",
]
