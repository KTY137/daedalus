from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import pytest

from daedalus.spine import effect_boundary
from daedalus.spine.promotion_recovery_consumption_registry import (
    install_promotion_recovery_consumption_inventory,
)
from daedalus.spine.promotion_recovery_consumption_registry_report import (
    inspect_promotion_recovery_consumption_registry,
)


EXPECTED_IDS = (
    "kernel.promotion_recovery_consumption.initialize",
    "kernel.promotion_recovery_consumption.consume",
)
EXPECTED_TARGETS = {
    "daedalus.kernel.promotion_recovery_consumption:"
    "PromotionRecoveryConsumptionLedger.__init__",
    "daedalus.kernel.promotion_recovery_consumption:"
    "PromotionRecoveryConsumptionLedger.consume",
}


def _fake_boundary() -> SimpleNamespace:
    retained = effect_boundary.ENTRYPOINTS[: -len(EXPECTED_IDS)]

    def registry_sha256(registry=retained):
        return str(len(registry))

    def begin_effect(entrypoint_id, requested_effects, decisions, *, registry=None):
        return entrypoint_id, requested_effects, decisions, registry

    def check_conformance(root, *, registry=retained):
        return root, registry

    return SimpleNamespace(
        EntrypointSpec=effect_boundary.EntrypointSpec,
        GuardAnchor=effect_boundary.GuardAnchor,
        Surface=effect_boundary.Surface,
        Effect=effect_boundary.Effect,
        Wiring=effect_boundary.Wiring,
        ENTRYPOINTS=retained,
        REGISTRY_BY_ID=MappingProxyType({row.id: row for row in retained}),
        GUARD_CONTRACT_IMPLEMENTED=MappingProxyType(
            {
                name: implemented
                for name, implemented in effect_boundary.GUARD_CONTRACT_IMPLEMENTED.items()
                if name != "promotion.owner_recovery_decision"
            }
        ),
        POLICY_CONTRACTS=frozenset(
            name
            for name in effect_boundary.POLICY_CONTRACTS
            if name != "promotion.owner_recovery_decision"
        ),
        registry_sha256=registry_sha256,
        begin_effect=begin_effect,
        check_conformance=check_conformance,
        _surface_for_function=lambda model, qualname: None,
    )


def test_package_initialization_installs_exact_rows_guard_and_defaults() -> None:
    assert tuple(row.id for row in effect_boundary.ENTRYPOINTS[-2:]) == EXPECTED_IDS
    initialize = effect_boundary.REGISTRY_BY_ID[EXPECTED_IDS[0]]
    consume = effect_boundary.REGISTRY_BY_ID[EXPECTED_IDS[1]]

    assert initialize.wiring is effect_boundary.Wiring.UNGUARDED
    assert initialize.guard_contracts == ()
    assert consume.wiring is effect_boundary.Wiring.LOCAL_GUARDS
    assert consume.guard_contracts == ("promotion.owner_recovery_decision",)
    assert initialize.effects == consume.effects == (
        effect_boundary.Effect.FILESYSTEM_WRITE,
    )
    assert effect_boundary.GUARD_CONTRACT_IMPLEMENTED[
        "promotion.owner_recovery_decision"
    ] is True
    assert effect_boundary.registry_sha256.__defaults__ == (
        effect_boundary.ENTRYPOINTS,
    )
    assert (
        effect_boundary.begin_effect.__kwdefaults__["registry"]
        is effect_boundary.REGISTRY_BY_ID
    )
    assert (
        effect_boundary.check_conformance.__kwdefaults__["registry"]
        is effect_boundary.ENTRYPOINTS
    )


def test_exact_scanner_hook_discovers_only_the_two_writer_methods(tmp_path) -> None:
    module = tmp_path / "daedalus" / "kernel" / "promotion_recovery_consumption.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        """
class PromotionRecoveryConsumptionLedger:
    def __init__(self, path):
        path.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self):
        self._connect_writer()

    def _connect_writer(self):
        return None

    def consume(self):
        self._connect_writer()

    def verify_consumption(self):
        return None
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'scanner-fixture'\nversion = '0'\n",
        encoding="utf-8",
    )

    discoveries, findings = effect_boundary.discover_entrypoints(tmp_path)
    assert not [row for row in findings if row.severity == "blocker"]
    targets = {row.target for row in discoveries}
    assert targets == EXPECTED_TARGETS
    assert all(
        row.effects == (effect_boundary.Effect.FILESYSTEM_WRITE,)
        for row in discoveries
    )


def test_machine_report_is_revision_bound_and_honest() -> None:
    report = inspect_promotion_recovery_consumption_registry(
        source_revision="1" * 40
    )
    replay = inspect_promotion_recovery_consumption_registry(
        source_revision="1" * 40
    )
    changed = inspect_promotion_recovery_consumption_registry(
        source_revision="2" * 40
    )

    assert report == replay
    assert report.report_sha256 != changed.report_sha256
    assert report.canonical_registry_integrated is True
    assert report.guard_contract_integrated is True
    assert report.scanner_integrated is True
    assert report.closed is False
    assert report.blockers == (
        "constructor-performs-unguarded-schema-initialization",
        "consume-is-locally-owner-guarded-but-not-effect-lease-central",
        "runtime-conformance-kill-switch-and-docker-sandbox-not-composed",
    )
    assert tuple(row["id"] for row in report.exact_rows) == EXPECTED_IDS


@pytest.mark.parametrize(
    "revision",
    ["", "abc", "A" * 40, "g" * 40, "0" * 39, "0" * 65],
)
def test_machine_report_refuses_malformed_revisions(revision: str) -> None:
    with pytest.raises(ValueError, match="source_revision"):
        inspect_promotion_recovery_consumption_registry(
            source_revision=revision
        )


def test_noncentral_rows_cannot_open_the_generic_effect_boundary() -> None:
    for entrypoint_id in EXPECTED_IDS:
        with pytest.raises(effect_boundary.EffectStartRefused, match="not central"):
            effect_boundary.begin_effect(
                entrypoint_id,
                (effect_boundary.Effect.FILESYSTEM_WRITE,),
                (),
            )


def test_installer_is_exactly_idempotent_on_an_isolated_boundary() -> None:
    boundary = _fake_boundary()
    install_promotion_recovery_consumption_inventory(boundary)
    first_rows = boundary.ENTRYPOINTS
    first_registry = boundary.REGISTRY_BY_ID
    first_scanner = boundary._surface_for_function

    install_promotion_recovery_consumption_inventory(boundary)

    assert boundary.ENTRYPOINTS == first_rows
    assert dict(boundary.REGISTRY_BY_ID) == dict(first_registry)
    assert boundary._surface_for_function is first_scanner
    assert tuple(row.id for row in boundary.ENTRYPOINTS[-2:]) == EXPECTED_IDS
    assert boundary.GUARD_CONTRACT_IMPLEMENTED[
        "promotion.owner_recovery_decision"
    ] is True
    assert boundary.registry_sha256.__defaults__ == (boundary.ENTRYPOINTS,)
    assert boundary.begin_effect.__kwdefaults__["registry"] is boundary.REGISTRY_BY_ID
    assert boundary.check_conformance.__kwdefaults__["registry"] is boundary.ENTRYPOINTS


def test_installer_refuses_partial_rows_and_conflicting_guard() -> None:
    partial = _fake_boundary()
    install_promotion_recovery_consumption_inventory(partial)
    partial.ENTRYPOINTS = partial.ENTRYPOINTS[:-1]
    partial.REGISTRY_BY_ID = MappingProxyType(
        {row.id: row for row in partial.ENTRYPOINTS}
    )
    with pytest.raises(RuntimeError, match="partially"):
        install_promotion_recovery_consumption_inventory(partial)

    conflict = _fake_boundary()
    guards = dict(conflict.GUARD_CONTRACT_IMPLEMENTED)
    guards["promotion.owner_recovery_decision"] = False
    conflict.GUARD_CONTRACT_IMPLEMENTED = MappingProxyType(guards)
    conflict.POLICY_CONTRACTS = frozenset(guards)
    with pytest.raises(RuntimeError, match="conflicting.*guard"):
        install_promotion_recovery_consumption_inventory(conflict)
