"""Trust regressions for the MissionSupervisor attempt-identity projection."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.ikarus_supervisor import _canonical_attempt_identity  # noqa: E402


def _result(attempt_id: str = "attempt-1", *, base_revision: str = "a" * 40):
    return SimpleNamespace(
        effect_key=attempt_id,
        branch=attempt_id,
        base_revision=base_revision,
    )


def _contracts(
    attempt_id: str = "attempt-1",
    *,
    mission_id: str = "mission-1",
    task_id: str = "work-item-1",
    base_revision: str = "a" * 40,
):
    return SimpleNamespace(
        attempt=SimpleNamespace(
            attempt_id=attempt_id,
            mission_id=mission_id,
            task_id=task_id,
            base_revision=base_revision,
        )
    )


def test_canonical_attempt_contract_is_the_only_identity_source() -> None:
    attempt_id, error = _canonical_attempt_identity(
        _result(),
        _contracts(),
        mission_id="mission-1",
        work_item_id="work-item-1",
    )
    assert attempt_id == "attempt-1"
    assert error is None

    # A transport/effect identity without a canonical contract must never be
    # promoted into the Work Pulse / state-ledger attempt_id field.
    attempt_id, error = _canonical_attempt_identity(
        _result(),
        None,
        mission_id="mission-1",
        work_item_id="work-item-1",
    )
    assert attempt_id is None
    assert "AttemptContract is unavailable" in (error or "")


def test_transport_branch_cannot_override_canonical_attempt_identity() -> None:
    result = _result("transport-branch")
    attempt_id, error = _canonical_attempt_identity(
        result,
        _contracts(attempt_id="canonical-attempt"),
        mission_id="mission-1",
        work_item_id="work-item-1",
    )
    assert attempt_id is None
    assert "effect/branch identity" in (error or "")


@pytest.mark.parametrize(
    ("contracts", "message"),
    [
        (_contracts(mission_id="mission-foreign"), "mission_id"),
        (_contracts(task_id="work-item-foreign"), "task_id"),
        (_contracts(base_revision="b" * 40), "base_revision"),
    ],
)
def test_canonical_attempt_must_bind_mission_work_item_and_revision(
    contracts, message: str
) -> None:
    attempt_id, error = _canonical_attempt_identity(
        _result(),
        contracts,
        mission_id="mission-1",
        work_item_id="work-item-1",
    )
    assert attempt_id is None
    assert message in (error or "")
