"""Transient retention probe for the atomic Boolean 2-cell observer.

This probe intentionally reuses the real Gate-1 voltage ignition fixture rather
than another synthetic relation-block example.  The question is whether the
experimental square observer can detect a realistic cross-plane partial rename
that the authoritative Fourfold compiler would otherwise miss.

The expected result is negative utility: the reference compiler refuses the
mixed revision before a target FourfoldSnapshot exists, so no trustworthy
source/target relation-block square can even be formed.  The test is diagnostic
Evidence only and is removed after its exact-head run is retained.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from daedalus.twin._reference_common import ReferenceCompileError
from daedalus.twin.reference_compiler import compile_reference_project

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ignition" / "voltage"
BASE = "1" * 40
PARTIAL = "2" * 40
NOW = "2026-08-31T17:10:00Z"


def test_real_voltage_partial_rename_is_refused_before_a_target_square_can_exist(
    tmp_path: Path,
) -> None:
    """A mixed Code/Type rename never reaches a Fourfold 2-cell observer.

    This is the same defect shape pinned by the Gate-1 crash fault: code has
    moved to ``bias_voltage`` while the manifest/data/knowledge side still
    asserts ``voltage``.  The authoritative compiler validates those claims
    before producing a snapshot.  Therefore the experimental Boolean square
    observer cannot add an earlier safety signal for this failure class: its
    target relation block would require a target FourfoldSnapshot that does not
    exist.
    """
    base = compile_reference_project(
        FIXTURE,
        source_revision=BASE,
        created_at=NOW,
        trace_id="g1-tensor-01ac-base",
    )
    assert base.snapshot.source_revision == BASE
    assert base.snapshot.repository_id == "daedalus/ignition-field-fixture"

    partial = tmp_path / "partial"
    shutil.copytree(FIXTURE, partial)
    models = partial / "src/ignition_app/models.py"
    models.write_text(
        models.read_text(encoding="utf-8").replace(
            "voltage", "bias_voltage"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ReferenceCompileError, match="Event.voltage"):
        compile_reference_project(
            partial,
            source_revision=PARTIAL,
            created_at=NOW,
            trace_id="g1-tensor-01ac-partial",
        )
