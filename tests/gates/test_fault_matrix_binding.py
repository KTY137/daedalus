"""Binding the whole-matrix verdict is fail-closed, and binding is not closure.

These are policy tests, so every fixture is built here rather than read out of a
dated evidence folder: the gate rule must hold for any verdict, not only for the
one run that happens to be landed.  The landed bundle is bound for real in
``tests/gates/test_gate_report_matrix_binding.py`` and round-tripped in
``tests/runtimes/test_whole_fault_matrix.py``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from daedalus.gates.fault_matrix_binding import (
    FaultMatrixBinding,
    bind_fault_matrix_evidence,
)
from daedalus.spine.envelope import canonical_json


REVISION = "c" * 40
OTHER_REVISION = "d" * 40
SCOPING_DOC = "docs/GATE0_LINUX_FAULT_SCOPING_DECISION.md"
MATRIX_SHA = f"{9001:064x}"
CATALOG_SHA = f"{9002:064x}"

BLOCKED_SCENARIOS = (
    "runtime.egress.unauthorized-endpoint",
    "runtime.process.oom",
)
MISSING_SCENARIOS = ("runtime.live-envelope.expiry",)
BLOCKED_ROWS = tuple(f"fault.blocked:{name}" for name in BLOCKED_SCENARIOS)
MISSING_ROWS = tuple(f"fault.missing:{name}" for name in MISSING_SCENARIOS)
ALL_ROWS = tuple(sorted(BLOCKED_ROWS + MISSING_ROWS))


def _verdict_payload(
    *,
    revision: str = REVISION,
    key_class: str = "development",
    blockers: tuple[str, ...] = ALL_ROWS,
) -> dict[str, Any]:
    trusted = sorted(f"{index + 1:064x}" for index in range(2))
    attestations = sorted(f"{index + 1001:064x}" for index in range(2))
    grouped: dict[str, list[str]] = {}
    for blocker in sorted(blockers):
        grouped.setdefault(blocker.split(":", 1)[0], []).append(blocker)
    return {
        "source_revision": revision,
        "catalog_sha256": CATALOG_SHA,
        "catalog_scenarios": 24,
        "matrix_sha256": MATRIX_SHA,
        "observations": 2,
        "columns": {
            "deterministic-fixture": {
                "issuer_id": "issuer.fixture",
                "key_class": key_class,
                "observations": 2,
                "attestations": 2,
            }
        },
        "closed": not blockers,
        "blocker_count": len(blockers),
        "blockers_by_class": {name: sorted(rows) for name, rows in sorted(grouped.items())},
        "verification": {
            "fault_verification": {
                "matrix_sha256": MATRIX_SHA,
                "catalog_sha256": CATALOG_SHA,
                "source_revision": revision,
                "trusted_observation_sha256s": trusted,
                "blockers": sorted(blockers),
                "closed": not blockers,
            },
            "attestation_sha256s": attestations,
            "verified_at": "2026-08-17T20:46:48.766566+00:00",
            "closed": not blockers,
        },
    }


def _receipt_payload(
    *,
    revision: str = REVISION,
    key_class: str = "development",
    scenarios: tuple[str, ...] = BLOCKED_SCENARIOS,
    matrix_sha: str = MATRIX_SHA,
    scoped_by: str | None = SCOPING_DOC,
) -> dict[str, Any]:
    return {
        "schema": "daedalus-gate0-whole-matrix-receipt/1",
        "source_revision": revision,
        "matrix": {"matrix_sha256": matrix_sha},
        "key_material": {"class": key_class},
        "blockers": {
            "fault.blocked": {
                "scenarios": list(scenarios),
                "scoped_by": scoped_by,
            }
        },
    }


def _repo(
    tmp_path: Path,
    *,
    verdict: dict[str, Any] | None = None,
    receipt: dict[str, Any] | None = None,
    with_decision: bool = True,
    dir_name: str = "gate0-matrix-2026-08-17",
) -> Path:
    root = tmp_path / "repo"
    evidence = root / "runs" / dir_name
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "whole-matrix-verdict.json").write_text(
        canonical_json(_verdict_payload() if verdict is None else verdict) + "\n",
        encoding="utf-8",
    )
    if receipt is not None:
        (evidence / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    if with_decision:
        decision = root / SCOPING_DOC
        decision.parent.mkdir(parents=True, exist_ok=True)
        decision.write_text("scoping decision fixture\n", encoding="utf-8")
    return root


def test_no_evidence_is_a_named_blocker_never_a_silent_pass(tmp_path: Path) -> None:
    binding = bind_fault_matrix_evidence(tmp_path, source_revision=REVISION)
    assert binding.bound is False
    assert binding.attests_closure is False
    assert binding.failures == ("whole-matrix:unbound:no-verdict-artifact",)
    assert "blocker:fault_matrix.unbound:no-verdict-artifact" in binding.diagnostics


def test_an_empty_explicit_evidence_dir_is_a_named_blocker(tmp_path: Path) -> None:
    binding = bind_fault_matrix_evidence(
        tmp_path, source_revision=REVISION, evidence_dir=tmp_path / "nowhere"
    )
    assert binding.failures == ("whole-matrix:unbound:no-verdict-artifact",)
    assert binding.bound is False


def test_a_dev_key_bundle_binds_open_and_declares_only_the_scoped_rows(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path, receipt=_receipt_payload())
    binding = bind_fault_matrix_evidence(root, source_revision=REVISION)
    assert binding.bound is True
    assert binding.attests_closure is False
    assert binding.declared == tuple(sorted(BLOCKED_ROWS))
    assert binding.failures == tuple(sorted(MISSING_ROWS))
    assert binding.key_classes == ("development",)
    assert binding.matrix_sha256 == MATRIX_SHA
    for row in BLOCKED_ROWS:
        assert f"declared:fault_matrix.scoped:{row}@{SCOPING_DOC}" in binding.diagnostics
    assert (
        "info:fault_matrix.trust:signatures-not-reverified-at-report-time"
        in binding.diagnostics
    )


def test_without_a_receipt_no_blocked_row_is_declared(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    binding = bind_fault_matrix_evidence(root, source_revision=REVISION)
    assert binding.declared == ()
    assert binding.failures == ALL_ROWS
    assert (
        "info:fault_matrix.declaration_refused:receipt-missing-or-malformed"
        in binding.diagnostics
    )


def test_a_declaration_without_the_decision_document_keeps_every_blocked_row(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path, receipt=_receipt_payload(), with_decision=False)
    binding = bind_fault_matrix_evidence(root, source_revision=REVISION)
    assert binding.declared == ()
    assert binding.failures == ALL_ROWS
    assert any(
        row.startswith("info:fault_matrix.declaration_refused:scoping-decision-absent")
        for row in binding.diagnostics
    )


def test_a_receipt_naming_no_decision_declares_nothing(tmp_path: Path) -> None:
    root = _repo(tmp_path, receipt=_receipt_payload(scoped_by=None))
    binding = bind_fault_matrix_evidence(root, source_revision=REVISION)
    assert binding.declared == ()
    assert (
        "info:fault_matrix.declaration_refused:no-scoping-decision-named"
        in binding.diagnostics
    )


def test_a_receipt_escaping_the_repository_declares_nothing(tmp_path: Path) -> None:
    root = _repo(tmp_path, receipt=_receipt_payload(scoped_by="../../etc/passwd"))
    binding = bind_fault_matrix_evidence(root, source_revision=REVISION)
    assert binding.declared == ()
    assert (
        "info:fault_matrix.declaration_refused:no-scoping-decision-named"
        in binding.diagnostics
    )


def test_a_receipt_that_is_not_bound_to_this_verdict_declares_nothing(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path, receipt=_receipt_payload(matrix_sha="0" * 64))
    binding = bind_fault_matrix_evidence(root, source_revision=REVISION)
    assert binding.declared == ()
    assert binding.failures == ALL_ROWS
    assert (
        "info:fault_matrix.declaration_refused:receipt-not-bound-to-this-verdict"
        in binding.diagnostics
    )


def test_a_receipt_that_widens_the_scope_declares_nothing(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        receipt=_receipt_payload(
            scenarios=BLOCKED_SCENARIOS + MISSING_SCENARIOS,
        ),
    )
    binding = bind_fault_matrix_evidence(root, source_revision=REVISION)
    assert binding.declared == ()
    assert binding.failures == ALL_ROWS
    assert (
        "info:fault_matrix.declaration_refused:"
        "scoped-scenarios-do-not-match-the-verdict" in binding.diagnostics
    )


def test_a_receipt_claiming_production_custody_over_a_dev_run_is_a_blocker(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path, receipt=_receipt_payload(key_class="production"))
    binding = bind_fault_matrix_evidence(root, source_revision=REVISION)
    assert "whole-matrix:key-class-contradiction:production" in binding.failures
    assert binding.attests_closure is False


def test_the_custody_cross_check_holds_even_with_nothing_to_declare(
    tmp_path: Path,
) -> None:
    root = _repo(
        tmp_path,
        verdict=_verdict_payload(blockers=()),
        receipt=_receipt_payload(key_class="production", scenarios=()),
    )
    binding = bind_fault_matrix_evidence(root, source_revision=REVISION)
    assert "whole-matrix:key-class-contradiction:production" in binding.failures
    assert binding.attests_closure is False


@pytest.mark.parametrize(
    "mutation",
    (
        {"blocker_count": 0},
        {"closed": True},
        {"observations": 99},
    ),
)
def test_a_tampered_verdict_refuses_to_bind(tmp_path: Path, mutation: dict[str, Any]) -> None:
    payload = _verdict_payload()
    payload.update(mutation)
    root = _repo(tmp_path, verdict=payload, receipt=_receipt_payload())
    binding = bind_fault_matrix_evidence(root, source_revision=REVISION)
    assert binding.bound is False
    assert binding.failures == ("whole-matrix:unbound:verdict-invalid",)
    assert binding.declared == ()


def test_a_verdict_stored_in_non_canonical_form_refuses_to_bind(tmp_path: Path) -> None:
    """The same instant written in another offset is a different artifact."""

    payload = _verdict_payload()
    payload["verification"]["verified_at"] = "2026-08-17T22:46:48.766566+02:00"
    root = _repo(tmp_path, verdict=payload, receipt=_receipt_payload())
    binding = bind_fault_matrix_evidence(root, source_revision=REVISION)
    assert binding.bound is False
    assert binding.failures == ("whole-matrix:unbound:verdict-invalid",)


def test_a_receipt_of_another_schema_declares_nothing(tmp_path: Path) -> None:
    receipt = _receipt_payload()
    receipt["schema"] = "something-else/1"
    root = _repo(tmp_path, receipt=receipt)
    binding = bind_fault_matrix_evidence(root, source_revision=REVISION)
    assert binding.declared == ()
    assert binding.failures == ALL_ROWS
    assert (
        "info:fault_matrix.declaration_refused:receipt-missing-or-malformed"
        in binding.diagnostics
    )


def test_a_verdict_from_another_revision_binds_but_blocks(tmp_path: Path) -> None:
    root = _repo(tmp_path, receipt=_receipt_payload())
    binding = bind_fault_matrix_evidence(root, source_revision=OTHER_REVISION)
    assert binding.bound is True
    assert f"whole-matrix:observed-at-other-revision:{REVISION}" in binding.failures
    assert binding.attests_closure is False


def test_ambiguous_evidence_refuses_rather_than_picking_one(tmp_path: Path) -> None:
    """Two verdicts claiming the same revision are genuine ambiguity."""

    root = _repo(tmp_path, receipt=_receipt_payload())
    second = root / "runs" / "gate0-matrix-2026-08-18"
    second.mkdir(parents=True)
    (second / "whole-matrix-verdict.json").write_text(
        canonical_json(_verdict_payload()) + "\n", encoding="utf-8"
    )
    binding = bind_fault_matrix_evidence(root, source_revision=REVISION)
    assert binding.bound is False
    assert binding.failures == ("whole-matrix:unbound:ambiguous-evidence:2",)


def test_no_candidate_at_the_cited_revision_names_the_candidates(
    tmp_path: Path,
) -> None:
    """Accumulated evidence with zero revision matches is a miss, not a count."""

    root = _repo(tmp_path, receipt=_receipt_payload())
    second = root / "runs" / "gate0-matrix-2026-08-18"
    second.mkdir(parents=True)
    (second / "whole-matrix-verdict.json").write_text(
        canonical_json(_verdict_payload()) + "\n", encoding="utf-8"
    )
    binding = bind_fault_matrix_evidence(root, source_revision=OTHER_REVISION)
    assert binding.bound is False
    assert binding.failures == (
        "whole-matrix:unbound:no-verdict-at-cited-revision:"
        "candidates=gate0-matrix-2026-08-17,gate0-matrix-2026-08-18",
    )


def test_ambiguity_resolves_when_exactly_one_bundle_owns_this_revision(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path, receipt=_receipt_payload())
    second = root / "runs" / "gate0-matrix-2026-08-18"
    second.mkdir(parents=True)
    (second / "whole-matrix-verdict.json").write_text(
        canonical_json(_verdict_payload(revision=OTHER_REVISION)) + "\n",
        encoding="utf-8",
    )
    binding = bind_fault_matrix_evidence(root, source_revision=OTHER_REVISION)
    assert binding.bound is True
    assert binding.observed_revision == OTHER_REVISION


def test_a_dev_key_run_may_not_carry_a_security_boundary_claim(tmp_path: Path) -> None:
    root = _repo(tmp_path, receipt=_receipt_payload())
    binding = bind_fault_matrix_evidence(
        root, source_revision=REVISION, security_boundary_claimed=True
    )
    assert (
        "whole-matrix:security-boundary-unproven:key-material-development"
        in binding.failures
    )
    assert binding.attests_closure is False


def test_a_production_closed_verdict_at_this_revision_can_attest_closure(
    tmp_path: Path,
) -> None:
    root = _repo(
        tmp_path,
        verdict=_verdict_payload(key_class="production", blockers=()),
    )
    binding = bind_fault_matrix_evidence(
        root, source_revision=REVISION, security_boundary_claimed=True
    )
    assert binding.bound is True
    assert binding.failures == ()
    assert binding.attests_closure is True
    assert binding.key_classes == ("production",)


def test_the_same_closed_verdict_under_dev_keys_cannot(tmp_path: Path) -> None:
    root = _repo(tmp_path, verdict=_verdict_payload(blockers=()))
    binding = bind_fault_matrix_evidence(
        root, source_revision=REVISION, security_boundary_claimed=True
    )
    assert binding.attests_closure is False
    assert (
        "whole-matrix:security-boundary-unproven:key-material-development"
        in binding.failures
    )


def test_a_closed_production_verdict_from_another_revision_cannot(
    tmp_path: Path,
) -> None:
    root = _repo(
        tmp_path,
        verdict=_verdict_payload(key_class="production", blockers=()),
    )
    binding = bind_fault_matrix_evidence(
        root, source_revision=OTHER_REVISION, security_boundary_claimed=True
    )
    assert binding.attests_closure is False
    assert (
        "whole-matrix:security-boundary-unproven:observed-at-other-revision"
        in binding.failures
    )


def test_declared_rows_alone_still_block_a_boundary_claim(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        verdict=_verdict_payload(key_class="production", blockers=BLOCKED_ROWS),
        receipt=_receipt_payload(key_class="production"),
    )
    binding = bind_fault_matrix_evidence(
        root, source_revision=REVISION, security_boundary_claimed=True
    )
    assert binding.declared == tuple(sorted(BLOCKED_ROWS))
    assert binding.attests_closure is False
    assert (
        "whole-matrix:security-boundary-unproven:scoped-rows-are-declared-not-proven"
        in binding.failures
    )


def test_a_binding_with_findings_can_never_claim_closure() -> None:
    with pytest.raises(ValueError, match="cannot attest closure"):
        FaultMatrixBinding(
            bound=True,
            attests_closure=True,
            failures=("fault.missing:anything",),
            diagnostics=(),
        )
    with pytest.raises(ValueError, match="cannot attest closure"):
        FaultMatrixBinding(
            bound=False, attests_closure=True, failures=(), diagnostics=()
        )
