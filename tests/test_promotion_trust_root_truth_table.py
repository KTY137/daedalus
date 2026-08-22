"""The D5 acceptance truth table, executed.

The expected column is not written here. It is READ OUT OF THE COMMITTED PLAN
(``docs/inventory/2026-08-21/GIGA_PLAN_2026-08-22.md``, section
``### D5 acceptance truth table``), which was written before this
implementation existed. That is the whole point of a precommitted table: if the
oracle lived in this file, the implementer would be writing both the question
and the answer, and the test would only prove the code agrees with itself.

Round 2, seat 3's objection, restated: "hybrid with B as root" is meaningless
until every cell has a verdict, because an implementation can treat the HMAC
factor as mandatory, advisory or ignored and still truthfully describe itself
as "B as root". These four cases are what distinguishes the three.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from daedalus.kernel import promotion_trust_root as root_mod
from daedalus.kernel.promotion_trust_root import (
    TRUST_ROOT_MODE,
    TRUTH_TABLE,
    ApprovalVerdict,
    SecondFactorOutcome,
    evaluate_promotion_trust,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GIGA_PLAN = REPO_ROOT / "docs" / "inventory" / "2026-08-21" / "GIGA_PLAN_2026-08-22.md"

CANDIDATE = "a" * 64
EVIDENCE = "b" * 64
REVISION = "c" * 40


def _committed_table() -> dict[tuple[bool, bool], str]:
    """The hybrid column of the committed table, keyed (B valid, HMAC valid)."""
    text = GIGA_PLAN.read_text(encoding="utf-8")
    start = text.index("### D5 acceptance truth table")
    block = text[start : start + 4000]
    table: dict[tuple[bool, bool], str] = {}
    row = re.compile(
        r"^\|\s*(valid|invalid)\s*\|\s*(valid|invalid)\s*\|"
        r"[^|]*\|[^|]*\|\s*(PROMOTE|REJECT)",
        re.MULTILINE,
    )
    for match in row.finditer(block):
        table[(match.group(1) == "valid", match.group(2) == "valid")] = match.group(3)
    return table


def _approved_root() -> ApprovalVerdict:
    return ApprovalVerdict(
        approved=True,
        reason="test double: owner signature verified",
        candidate_sha256=CANDIDATE,
        tag=f"promote/{CANDIDATE}",
        owner_approval_ref="artifact-locator:sha256:" + ("d" * 64),
        signer="owner@example",
        expires_at="2026-08-22T23:00:00+00:00",
        nonce="nonce-truth-table",
        evidence_sha256=EVIDENCE,
        source_revision=REVISION,
        signed_at="2026-08-22T11:00:00+00:00",
    )


def _refused_root() -> ApprovalVerdict:
    return ApprovalVerdict(
        approved=False,
        reason="test double: no approval tag in this repository",
        candidate_sha256=CANDIDATE,
        tag=f"promote/{CANDIDATE}",
    )


def _decide(tmp_path: Path, *, root_valid: bool, hmac_valid: bool, records: list):
    return evaluate_promotion_trust(
        repo_root=tmp_path,
        candidate_artifact_sha256=CANDIDATE,
        evidence_packet_sha256=EVIDENCE,
        source_revision=REVISION,
        stage="preauthorization",
        _root_verifier=lambda *a, **k: (
            _approved_root() if root_valid else _refused_root()
        ),
        _second_factor=SecondFactorOutcome(
            valid=hmac_valid,
            reason="test double",
            consumption_sha256="e" * 64 if hmac_valid else None,
        ),
        _record_sink=lambda line: (records.append(dict(line)) or ("f" * 64)),
    )


def test_the_committed_plan_still_carries_all_four_hybrid_cells() -> None:
    committed = _committed_table()
    assert set(committed) == {(True, True), (True, False), (False, True), (False, False)}


@pytest.mark.parametrize(
    "root_valid,hmac_valid",
    [(True, True), (True, False), (False, True), (False, False)],
)
def test_each_cell_matches_the_precommitted_plan(
    tmp_path: Path, root_valid: bool, hmac_valid: bool
) -> None:
    expected = _committed_table()[(root_valid, hmac_valid)]
    records: list = []
    decision = _decide(
        tmp_path, root_valid=root_valid, hmac_valid=hmac_valid, records=records
    )
    assert decision.outcome == expected
    assert decision.promote is (expected == "PROMOTE")
    # In-code table and committed table must agree cell for cell.
    assert TRUTH_TABLE[(root_valid, hmac_valid)] == expected


def test_valid_root_with_invalid_hmac_promotes_and_ledgers_the_divergence(
    tmp_path: Path,
) -> None:
    """Row 2. The cell that separates 'advisory' from 'mandatory' and 'ignored'."""
    records: list = []
    decision = _decide(tmp_path, root_valid=True, hmac_valid=False, records=records)
    assert decision.promote is True
    assert decision.record_note == "second-factor-mismatch-ledgered"
    assert len(records) == 1
    assert records[0]["hmac_valid"] is False
    assert records[0]["root_valid"] is True
    assert records[0]["record_note"] == "second-factor-mismatch-ledgered"
    # never silently dropped
    assert records[0]["hmac_reason"]


def test_valid_hmac_never_substitutes_for_an_invalid_root(tmp_path: Path) -> None:
    """Row 3. This is the cell option A would have got wrong."""
    records: list = []
    decision = _decide(tmp_path, root_valid=False, hmac_valid=True, records=records)
    assert decision.promote is False
    receipt = decision.deny_receipt()
    assert receipt["failing_factors"] == ["root:git-signed-tag"]
    assert "does not substitute" in decision.deny_reason
    assert records[0]["hmac_valid"] is True


@pytest.mark.parametrize(
    "root_valid,hmac_valid",
    [(True, True), (True, False), (False, True), (False, False)],
)
def test_every_reject_names_the_failing_factor(
    tmp_path: Path, root_valid: bool, hmac_valid: bool
) -> None:
    records: list = []
    decision = _decide(
        tmp_path, root_valid=root_valid, hmac_valid=hmac_valid, records=records
    )
    if decision.promote:
        pytest.skip("this cell promotes")
    receipt = decision.deny_receipt()
    assert receipt["failing_factors"]
    assert receipt["reason"]


def test_a_record_that_cannot_be_written_rejects_even_a_valid_root(
    tmp_path: Path,
) -> None:
    """Mandatory for the record: no record, no promotion."""

    def broken_sink(_line):
        raise OSError("second-factor ledger unavailable")

    decision = evaluate_promotion_trust(
        repo_root=tmp_path,
        candidate_artifact_sha256=CANDIDATE,
        evidence_packet_sha256=EVIDENCE,
        source_revision=REVISION,
        stage="preauthorization",
        _root_verifier=lambda *a, **k: _approved_root(),
        _second_factor=SecondFactorOutcome(valid=True, reason="test double"),
        _record_sink=broken_sink,
    )
    assert decision.promote is False
    assert "mandatory for the record" in decision.deny_reason


def test_the_mode_is_pinned_and_the_seams_are_declared(tmp_path: Path) -> None:
    assert TRUST_ROOT_MODE == "hybrid-b-as-root"
    records: list = []
    decision = _decide(tmp_path, root_valid=True, hmac_valid=True, records=records)
    # A decision that used a test seam must say so, so the production caller can
    # refuse it. See test_promotion_trust_root_single_caller.
    assert set(decision.seams_used) == {"_root_verifier", "_second_factor", "_record_sink"}


def test_the_root_verifier_never_raises() -> None:
    """A boundary that can raise is one a caller can treat as a pass."""
    source = inspect.getsource(root_mod.verify_promotion_approval)
    assert "except Exception" in source
    verdict = root_mod.verify_promotion_approval(
        "\x00 not a path at all",
        candidate_sha256=CANDIDATE,
        evidence_sha256=EVIDENCE,
        source_revision=REVISION,
    )
    assert verdict.approved is False
