"""Effect.SECRETS modeling: measured evidence and conformance visibility.

The static discovery pass cannot see secret material the way it sees process
or network sinks, so ``SECRET_MATERIAL_EVIDENCE`` anchors every SECRETS claim
to re-checkable source markers and ``check_conformance`` makes divergence
visible.  These tests pin the four failure directions and the consistency of
the shipped registry.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from daedalus.spine import effect_boundary as eb
from daedalus.spine.effect_boundary import (
    ENTRYPOINTS,
    SECRET_MATERIAL_EVIDENCE,
    Effect,
    SecretEvidence,
    Wiring,
    check_conformance,
)

ROOT = Path(__file__).resolve().parents[1]


def _strip_secrets(row_id: str) -> tuple:
    return tuple(
        dataclasses.replace(
            row,
            effects=tuple(e for e in row.effects if e is not Effect.SECRETS),
        )
        if row.id == row_id
        else row
        for row in ENTRYPOINTS
    )


def test_shipped_registry_is_secrets_consistent() -> None:
    """Claims and measured evidence agree byte-for-byte on the real tree."""
    report = check_conformance(ROOT)
    secrets_findings = [f for f in report.findings if "secrets" in f.code]
    assert secrets_findings == [], [
        (f.code, f.severity, f.subject) for f in secrets_findings
    ]
    claimed = {row.id for row in ENTRYPOINTS if Effect.SECRETS in row.effects}
    assert claimed == set(SECRET_MATERIAL_EVIDENCE)


def test_unmodeled_secret_material_is_a_gap_on_local_rows() -> None:
    report = check_conformance(ROOT, registry=_strip_secrets("provider.deepseek"))
    findings = [
        (f.code, f.severity)
        for f in report.findings
        if f.subject == "provider.deepseek" and "secrets" in f.code
    ]
    assert findings == [("registry.secrets_unmodeled", "gap")]


def test_unmodeled_secret_material_blocks_a_central_row() -> None:
    """A CENTRAL row's declared effects are the lease ceiling; an unmodeled
    secret surface there is a contract lie, not a migration gap."""
    spec = next(row for row in ENTRYPOINTS if row.id == "python.offload")
    assert spec.wiring is Wiring.CENTRAL
    report = check_conformance(ROOT, registry=_strip_secrets("python.offload"))
    findings = [
        (f.code, f.severity)
        for f in report.findings
        if f.subject == "python.offload" and "secrets" in f.code
    ]
    assert findings == [("registry.secrets_unmodeled", "blocker")]
    assert not report.structurally_conformant


def test_secrets_claim_without_evidence_is_flagged_for_review() -> None:
    registry = tuple(
        dataclasses.replace(row, effects=(*row.effects, Effect.SECRETS))
        if row.id == "cli.doctor"
        else row
        for row in ENTRYPOINTS
    )
    report = check_conformance(ROOT, registry=registry)
    findings = [
        (f.code, f.severity)
        for f in report.findings
        if f.subject == "cli.doctor" and "secrets" in f.code
    ]
    assert findings == [("registry.secrets_unevidenced", "review")]


def test_vanished_marker_is_a_stale_evidence_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        eb,
        "SECRET_MATERIAL_EVIDENCE",
        {
            "provider.deepseek": (
                SecretEvidence(
                    "daedalus.providers.deepseek",
                    "MARKER_THAT_DOES_NOT_EXIST",
                    "env:GONE",
                ),
            )
        },
    )
    report = check_conformance(ROOT)
    findings = [
        (f.code, f.severity)
        for f in report.findings
        if f.subject == "provider.deepseek" and "secrets" in f.code
    ]
    assert findings == [("registry.secrets_evidence_stale", "blocker")]


def test_custom_registries_are_not_constrained_by_absent_rows() -> None:
    """Fixture registries (empty or single-row) must not inherit production
    evidence obligations; deleted rows are caught by target checks instead."""
    report = check_conformance(ROOT, registry=())
    assert [f.code for f in report.findings if "secrets" in f.code] == []
