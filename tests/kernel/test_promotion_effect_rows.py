from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus.kernel.promotion_effect_inventory import build_promotion_effect_inventory
from daedalus.spine import effect_boundary
from daedalus.spine.promotion_effect_rows import install_promotion_effect_rows


ROOT = Path(__file__).resolve().parents[2]
REVISION = "a" * 40
IDS = (
    "kernel.promotion_execution.begin",
    "kernel.promotion_execution.complete",
    "kernel.promotion_execution.open",
)


def test_exact_local_rows_are_installed_in_canonical_registry() -> None:
    rows = {row.id: row for row in effect_boundary.ENTRYPOINTS if row.id.startswith("kernel.promotion_execution.")}
    assert tuple(sorted(rows)) == IDS
    assert rows["kernel.promotion_execution.open"].target.endswith("PromotionExecutionLedger.__init__")
    assert rows["kernel.promotion_execution.begin"].target.endswith("PromotionExecutionLedger.begin")
    assert rows["kernel.promotion_execution.complete"].target.endswith("PromotionExecutionLedger.complete")
    assert all(
        row.wiring is effect_boundary.Wiring.LOCAL_GUARDS
        and row.effects == (effect_boundary.Effect.FILESYSTEM_WRITE,)
        and row.guard_contracts == ("spine.intent_ledger",)
        for row in rows.values()
    )


def test_captured_registry_defaults_use_installed_authority() -> None:
    assert effect_boundary.registry_sha256.__defaults__ == (effect_boundary.ENTRYPOINTS,)
    assert effect_boundary.begin_effect.__kwdefaults__["registry"] is effect_boundary.REGISTRY_BY_ID
    assert effect_boundary.check_conformance.__kwdefaults__["registry"] is effect_boundary.ENTRYPOINTS


def test_scoped_inventory_reduces_to_four_not_central_blockers() -> None:
    report = build_promotion_effect_inventory(ROOT, source_revision=REVISION)
    expected = {"python.promote_candidates", *IDS}
    assert report.closed is False
    assert {row.entrypoint_id for row in report.findings} == expected
    assert all(row.blockers == ("registry.not_central:local_guards",) for row in report.findings)


def test_partial_or_conflicting_installation_refuses() -> None:
    opened = effect_boundary.REGISTRY_BY_ID["kernel.promotion_execution.open"]
    fake = SimpleNamespace(
        EntrypointSpec=effect_boundary.EntrypointSpec,
        GuardAnchor=effect_boundary.GuardAnchor,
        Surface=effect_boundary.Surface,
        Effect=effect_boundary.Effect,
        Wiring=effect_boundary.Wiring,
        ENTRYPOINTS=(opened,),
    )
    with pytest.raises(RuntimeError, match="partially or incorrectly"):
        install_promotion_effect_rows(fake)
