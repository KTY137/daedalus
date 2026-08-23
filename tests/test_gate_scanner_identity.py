"""The repository-write scanner refuses ambiguous identity; it never crashes.

Provenance: `docs/GATE0_V3_SCANNER_IDENTITY_DECISION.md` section 2.1 (the
position key is not injective) and section 2.4 (the resulting `ValueError`
escapes every declared fail-closed handler).  Options B and D of that packet
removed *today's* instances from `daedalus/`; they did not remove the
mechanism, so both fixtures below still reproduce the collision at HEAD.

These tests are the guard for the Phase-3 exit condition `scanner_error == 0`:
a scanner that dies takes every Gate-0 counter with it, because
`scripts/report_gate0_v3.py` then prints an error document with no counters at
all instead of a report.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from daedalus.gates import report_v3
from daedalus.gates.repository_write_inventory import (
    RepositoryWriteInventoryError,
    scan_repository_write_surfaces,
)
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2Error,
    scan_repository_write_surfaces_v2,
)
from daedalus.gates.repository_write_stdlib_delta import (
    scan_repository_write_stdlib_delta,
)


REVISION = "0" * 40

# Three chained links: the second and third are both named `<expression>.replace`
# at the receiver's line and column, so the two records are indistinguishable.
DUPLICATE_RECORD_SOURCE = (
    "from pathlib import Path\n"
    "\n"
    "\n"
    "def stage(src: Path, a: Path, b: Path, c: Path) -> None:\n"
    "    src.replace(a).replace(b).replace(c)\n"
)
# Two chained links: one named receiver plus one `<expression>` link.  The
# records differ, so the base scanner accepts them, but they occupy one
# position and the composition refuses.
DUPLICATE_POSITION_SOURCE = (
    "from pathlib import Path\n"
    "\n"
    "\n"
    "def stage(src: Path, tmp: Path, dst: Path) -> None:\n"
    "    src.replace(tmp).replace(dst)\n"
)
# The same mechanism in the additive stdlib scanner: chained generic sinks
# produce two identical `<expression>.write` findings at one position.  That
# container raises a bare ValueError which only the composer can convert.
DUPLICATE_SINK_SOURCE = (
    "def stage(handle) -> None:\n"
    "    handle.write('a').write('b').write('c')\n"
)
# One unchained write surface: decidable identity, one blocking record.
DECIDABLE_SOURCE = (
    "from pathlib import Path\n"
    "\n"
    "\n"
    "def stage(target: Path) -> None:\n"
    "    target.write_text('x', encoding='utf-8')\n"
)


def _fixture_repo(tmp_path: Path, body: str) -> Path:
    package = tmp_path / "daedalus"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "stage.py").write_text(body, encoding="utf-8")
    return tmp_path


def test_duplicate_records_refuse_with_the_declared_scanner_error(
    tmp_path: Path,
) -> None:
    root = _fixture_repo(tmp_path, DUPLICATE_RECORD_SOURCE)
    with pytest.raises(RepositoryWriteInventoryError) as caught:
        scan_repository_write_surfaces(root, source_revision=REVISION)
    # Not a bare ValueError: the declared refusal type is a RuntimeError, and
    # every caller's fail-closed handler is written against it.
    assert not isinstance(caught.value, ValueError)
    assert isinstance(caught.value.__cause__, ValueError)
    message = str(caught.value)
    assert "identity is not decidable" in message
    # The refusal names where the collision is, or it is not evidence.
    assert "daedalus/stage.py:5:4" in message


def test_duplicate_positions_refuse_at_the_composition_boundary(
    tmp_path: Path,
) -> None:
    root = _fixture_repo(tmp_path, DUPLICATE_POSITION_SOURCE)
    # The base records differ, so generation 1 accepts them ...
    base = scan_repository_write_surfaces(root, source_revision=REVISION)
    assert len(base.callsites) == 2
    # ... and generation 2 refuses instead of raising a bare ValueError from
    # a frozen dataclass outside any handler.
    with pytest.raises(RepositoryWriteInventoryV2Error) as caught:
        scan_repository_write_surfaces_v2(root, source_revision=REVISION)
    assert not isinstance(caught.value, ValueError)
    assert "identity is not decidable" in str(caught.value)


def test_stdlib_delta_identity_failure_is_converted_by_the_composer(
    tmp_path: Path,
) -> None:
    root = _fixture_repo(tmp_path, DUPLICATE_SINK_SOURCE)
    # The additive scanner's own container still raises a bare ValueError ...
    with pytest.raises(ValueError) as raw:
        scan_repository_write_stdlib_delta(root, source_revision=REVISION)
    assert "findings must be unique" in str(raw.value)
    # ... and the composer is the boundary that keeps it inside the declared
    # refusal taxonomy, so no caller sees an uncaught exception.
    with pytest.raises(RepositoryWriteInventoryV2Error):
        scan_repository_write_surfaces_v2(root, source_revision=REVISION)


@pytest.mark.parametrize(
    "body",
    [DUPLICATE_RECORD_SOURCE, DUPLICATE_POSITION_SOURCE, DUPLICATE_SINK_SOURCE],
)
def test_reporter_counts_a_scanner_refusal_instead_of_dying(
    tmp_path: Path,
    body: str,
) -> None:
    root = _fixture_repo(tmp_path, body)
    (
        digest,
        scan_input,
        files_scanned,
        generation,
        failures,
        diagnostics,
        schema,
        scanner_error,
        # since a3f20aa7 (B5) the evidence also returns the raw surface count,
        # the classification schema and the per-surface verdicts
        surfaces_total,
        classification_schema,
        verdicts,
    ) = report_v3._repository_write_evidence(root, source_revision=REVISION)
    assert scanner_error == 1
    assert schema is None
    assert digest is None
    assert scan_input is None
    assert files_scanned == 0
    assert generation == 0
    assert failures == ("inventory-refused",)
    assert diagnostics == ("blocker:repository_write_inventory:refused",)


def test_decidable_fixture_declares_its_inventory_schema_and_no_error(
    tmp_path: Path,
) -> None:
    root = _fixture_repo(tmp_path, DECIDABLE_SOURCE)
    (
        digest,
        scan_input,
        files_scanned,
        generation,
        failures,
        diagnostics,
        schema,
        scanner_error,
        # since a3f20aa7 (B5) the evidence also returns the raw surface count,
        # the classification schema and the per-surface verdicts
        surfaces_total,
        classification_schema,
        verdicts,
    ) = report_v3._repository_write_evidence(root, source_revision=REVISION)
    assert scanner_error == 0
    # Observed from the artifact the scanner produced, not asserted by the
    # reporter, so an option-A record-shape bump surfaces as a mismatch.
    assert schema == report_v3._INVENTORY_SCHEMA
    assert len(digest or "") == 64
    assert len(scan_input or "") == 64
    assert files_scanned == 2
    assert generation == 2
    assert failures
    # Since 2af73956 the diagnostics carry the raw syntactic blocker count
    # verbatim (the chain verifies, never derives); the fixture has one.
    assert diagnostics == ("repository_write_syntactic_blockers:1",)


def test_the_conversion_that_keeps_a_refusal_inside_the_declared_taxonomy() -> None:
    """Structural guard for the two edits this file's behaviour depends on."""

    base = inspect.getsource(scan_repository_write_surfaces)
    assert "except ValueError as exc:" in base
    assert "raise RepositoryWriteInventoryError(" in base

    composed = inspect.getsource(scan_repository_write_surfaces_v2)
    # The component call site must catch the frozen-dataclass ValueError; the
    # two declared refusal types are RuntimeError subclasses and cannot.
    assert "ValueError," in composed
    assert "except ValueError as exc:" in composed
    assert "raise RepositoryWriteInventoryV2Error(" in composed

    evidence = inspect.getsource(report_v3._repository_write_evidence)
    assert '("blocker:repository_write_inventory:refused",)' in evidence
