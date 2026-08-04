from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from daedalus.kernel.promotion_effect_inventory import (
    PromotionEffectInventoryError,
    REQUIREMENTS,
    build_promotion_effect_inventory,
    main,
    verify_promotion_effect_inventory,
)
from daedalus.spine.effect_boundary import ENTRYPOINTS, Effect, EntrypointSpec, Wiring


ROOT = Path(__file__).resolve().parents[2]
REVISION = "a" * 40
_PROMOTION_ROWS = {
    "python.promote_candidates",
    "kernel.promotion_execution.open",
    "kernel.promotion_execution.begin",
    "kernel.promotion_execution.complete",
}


def _central_registry() -> tuple[EntrypointSpec, ...]:
    return tuple(
        dataclasses.replace(row, wiring=Wiring.CENTRAL)
        if row.id in _PROMOTION_ROWS
        else row
        for row in ENTRYPOINTS
    )


def _copy_sources(tmp_path: Path) -> Path:
    copied: set[str] = set()
    for requirement in REQUIREMENTS:
        if requirement.source_path in copied:
            continue
        copied.add(requirement.source_path)
        source = ROOT / requirement.source_path
        target = tmp_path / requirement.source_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return tmp_path


def test_current_promotion_inventory_is_honestly_open() -> None:
    report = build_promotion_effect_inventory(ROOT, source_revision=REVISION)
    findings = {row.entrypoint_id: row for row in report.findings}
    assert not report.closed
    assert set(findings) == _PROMOTION_ROWS
    for entrypoint_id in _PROMOTION_ROWS:
        assert findings[entrypoint_id].status == "blocked"
        assert findings[entrypoint_id].blockers == (
            "registry.not_central:local_guards",
        )
    assert len(report.report_sha256) == 64


def test_exact_central_registry_and_live_wired_source_close_only_scoped_inventory(
    tmp_path: Path,
) -> None:
    root = _copy_sources(tmp_path)
    report = build_promotion_effect_inventory(
        root,
        source_revision=REVISION,
        registry=_central_registry(),
    )
    assert report.closed
    assert len(report.findings) == 4
    assert {row.status for row in report.findings} == {"central"}
    assert all(not row.blockers for row in report.findings)


def test_wrong_target_effects_and_guards_are_all_blocking() -> None:
    registry = list(_central_registry())
    index = next(
        position
        for position, row in enumerate(registry)
        if row.id == "kernel.promotion_execution.begin"
    )
    registry[index] = dataclasses.replace(
        registry[index],
        target="daedalus.kernel.promotion_execution:wrong",
        effects=(Effect.PROCESS_SPAWN,),
        guard_contracts=("containment.worktree",),
    )
    report = build_promotion_effect_inventory(
        ROOT,
        source_revision=REVISION,
        registry=tuple(registry),
    )
    finding = next(
        row
        for row in report.findings
        if row.entrypoint_id == "kernel.promotion_execution.begin"
    )
    assert finding.status == "mismatched"
    assert finding.blockers == (
        "registry.effects_mismatch",
        "registry.guards_mismatch",
        "registry.target_mismatch",
    )
    assert not report.closed


def test_duplicate_registry_identity_refuses_before_projection() -> None:
    registry = (*_central_registry(), _central_registry()[-1])
    with pytest.raises(PromotionEffectInventoryError, match="duplicate"):
        build_promotion_effect_inventory(
            ROOT,
            source_revision=REVISION,
            registry=registry,
        )


def test_missing_manager_install_source_anchor_refuses_closure(tmp_path: Path) -> None:
    root = _copy_sources(tmp_path)
    source = root / "daedalus" / "kairos" / "gated_writes.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "_install_promotion_manager_boundary(globals())",
            "_install_promotion_manager_boundary_removed(globals())",
        ),
        encoding="utf-8",
    )
    report = build_promotion_effect_inventory(
        root,
        source_revision=REVISION,
        registry=_central_registry(),
    )
    finding = next(
        row
        for row in report.findings
        if row.entrypoint_id == "python.promote_candidates"
    )
    assert finding.status == "blocked"
    assert finding.blockers == (
        "source.missing_call:_install_promotion_manager_boundary",
    )
    assert not report.closed


def test_missing_begin_source_anchor_refuses_closure(tmp_path: Path) -> None:
    root = _copy_sources(tmp_path)
    source = root / "daedalus" / "kernel" / "promotion_execution.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "record_intent(",
            "record_intent_removed(",
        ),
        encoding="utf-8",
    )
    report = build_promotion_effect_inventory(
        root,
        source_revision=REVISION,
        registry=_central_registry(),
    )
    finding = next(
        row
        for row in report.findings
        if row.entrypoint_id == "kernel.promotion_execution.begin"
    )
    assert finding.status == "blocked"
    assert finding.blockers == ("source.missing_call:record_intent",)
    assert not report.closed


def test_missing_open_source_anchor_refuses_closure(tmp_path: Path) -> None:
    root = _copy_sources(tmp_path)
    source = root / "daedalus" / "kernel" / "promotion_execution.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "open_gate0_spine_writer(path)",
            "open_gate0_spine_writer_removed(path)",
        ),
        encoding="utf-8",
    )
    report = build_promotion_effect_inventory(
        root,
        source_revision=REVISION,
        registry=_central_registry(),
    )
    finding = next(
        row
        for row in report.findings
        if row.entrypoint_id == "kernel.promotion_execution.open"
    )
    assert finding.status == "blocked"
    assert finding.blockers == (
        "source.missing_call:open_gate0_spine_writer",
    )
    assert not report.closed


def test_malformed_revision_and_missing_repository_refuse(tmp_path: Path) -> None:
    with pytest.raises(PromotionEffectInventoryError, match="40 lowercase"):
        build_promotion_effect_inventory(ROOT, source_revision="A" * 40)
    with pytest.raises(PromotionEffectInventoryError, match="unavailable"):
        build_promotion_effect_inventory(
            tmp_path / "missing",
            source_revision=REVISION,
        )


def test_report_is_deterministic_and_live_verification_rebuilds() -> None:
    first = build_promotion_effect_inventory(ROOT, source_revision=REVISION)
    second = build_promotion_effect_inventory(ROOT, source_revision=REVISION)
    assert first == second
    assert first.to_dict() == second.to_dict()
    assert verify_promotion_effect_inventory(
        first,
        ROOT,
        expected_source_revision=REVISION,
    ) == first
    with pytest.raises(PromotionEffectInventoryError, match="differs"):
        verify_promotion_effect_inventory(
            first,
            ROOT,
            expected_source_revision="b" * 40,
        )


def test_cli_is_stdout_only_and_require_closed_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(
        [
            str(ROOT),
            "--source-revision",
            REVISION,
            "--require-closed",
        ]
    )
    assert result == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "daedalus-promotion-effect-inventory/1"
    assert payload["closed"] is False
    assert len(payload["findings"]) == 4


def test_inventory_module_has_no_effect_or_authority_surface() -> None:
    source = (
        ROOT
        / "daedalus"
        / "kernel"
        / "promotion_effect_inventory.py"
    ).read_text(encoding="utf-8").lower()
    forbidden = (
        "issue_owner_approval",
        "consume_owner_approval",
        "subprocess",
        "sqlite3",
        "git worktree",
        "merge_pull_request",
        "promote_candidates(",
    )
    for token in forbidden:
        assert token not in source
