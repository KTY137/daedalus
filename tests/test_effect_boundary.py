from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from daedalus.spine.effect_boundary import (
    ENTRYPOINTS,
    Effect,
    EffectStartRefused,
    EntrypointSpec,
    GuardAnchor,
    GuardDecision,
    Surface,
    UnregisteredEntrypoint,
    Wiring,
    begin_effect,
    check_conformance,
    discover_entrypoints,
    registry_sha256,
)


ROOT = Path(__file__).resolve().parents[1]


def _central_spec(**overrides) -> EntrypointSpec:
    values = {
        "id": "python.fixture",
        "surface": Surface.PYTHON,
        "target": "daedalus.fixture:run",
        "effects": (Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN),
        "guard_contracts": ("provider.write_policy", "containment.attempt"),
        "wiring": Wiring.CENTRAL,
    }
    values.update(overrides)
    return EntrypointSpec(**values)


def _allowed_decisions() -> tuple[GuardDecision, ...]:
    return (
        GuardDecision("containment.attempt", True, "job=contained"),
        GuardDecision("provider.write_policy", True, "path=tests/fixture.py"),
    )


def _minimal_repo(tmp_path: Path, source: str, *, module: str = "rogue") -> Path:
    package = tmp_path / "daedalus"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / f"{module}.py").write_text(source, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    return tmp_path


def test_inventory_covers_the_package_but_not_yet_the_tools_it_now_sees() -> None:
    """The daedalus side is inventoried; tools/ is the gap the scan just found.

    This test used to assert the inventory was COMPLETE, and that was true only
    while the scan globbed ``root/"daedalus"`` and nothing else. MEASURED
    2026-07-30 by adding an effectful entrypoint under tools/ and watching the
    matrix not move: 18 of 19 python files there spawn processes, write files,
    mutate the repository or spend money -- `audit_swarm.py`, which has billed
    roughly 750 external calls, among them.

    Widening the scan did not create these findings. It stopped hiding them,
    and a test asserting completeness over a scope that excluded the gap was
    reporting the scope, not the truth. So the assertion is split: the package
    is covered, the tools are not, and Gate 0 stays red for a reason that is
    now named rather than unseen.
    """
    report = check_conformance(ROOT)
    blocker_codes = {(row.code, row.subject) for row in report.findings
                     if row.severity == "blocker"}

    # the package's own entrypoints are all declared
    assert ("entrypoint.unregistered", "daedalus.offload:offload") not in blocker_codes
    assert ("entrypoint.unregistered",
            "daedalus.kairos.gated_writes:promote_candidates") not in blocker_codes
    assert not any(code == "entrypoint.unregistered" and subject.startswith("daedalus.")
                   for code, subject in blocker_codes), (
        "a daedalus entrypoint stopped being declared")

    # Promotion and offload now have mechanically anchored central starts.
    assert ("gate0.unguarded_entrypoint", "python.offload") not in blocker_codes
    assert ("gate0.unguarded_entrypoint", "python.promote_candidates") not in blocker_codes
    assert next(row for row in ENTRYPOINTS if row.id == "python.offload").wiring is Wiring.CENTRAL

    # and the newly visible gap is real, named, and not silently tolerated
    unregistered_tools = {subject for code, subject in blocker_codes
                          if code == "entrypoint.unregistered"
                          and subject.startswith("tools.")}
    assert unregistered_tools, (
        "the scan no longer reaches tools/; a directory of effectful "
        "entrypoints would be invisible to the drift detector again")

    assert report.structurally_conformant is False
    assert report.gate0_closed is False
    assert report.to_dict()["security_boundary_claimed"] is False


def test_required_gate0_surfaces_have_explicit_rows() -> None:
    assert {row.surface for row in ENTRYPOINTS} == set(Surface)
    mcp = next(row for row in ENTRYPOINTS if row.id == "mcp.runtime")
    assert mcp.wiring is Wiring.ABSENT
    assert "does not implement an MCP runtime boundary" in mcp.notes


def test_offload_is_central_and_anchored_to_persisted_lease_consumption() -> None:
    row = next(item for item in ENTRYPOINTS if item.id == "python.offload")
    assert row.wiring is Wiring.CENTRAL
    assert row.migration == "complete for the python.offload entrypoint"
    assert any(anchor.call == "begin_effect" for anchor in row.anchors)
    receipt = begin_effect(
        row.id,
        row.effects,
        [GuardDecision(name, True, "artifact-locator:sha256:" + "a" * 64)
         for name in row.guard_contracts],
    )
    assert receipt.entrypoint_id == row.id


def test_unknown_entrypoint_is_refused() -> None:
    with pytest.raises(UnregisteredEntrypoint, match="not registered"):
        begin_effect("python.unknown", [Effect.FILESYSTEM_WRITE], ())


def test_noncentral_entrypoint_is_refused_even_with_positive_claims() -> None:
    spec = _central_spec(wiring=Wiring.LOCAL_GUARDS)
    with pytest.raises(EffectStartRefused, match="not central"):
        begin_effect(spec.id, spec.effects, _allowed_decisions(), registry={spec.id: spec})


def test_central_start_requires_declared_effects_and_all_guards() -> None:
    spec = _central_spec()
    registry = {spec.id: spec}

    with pytest.raises(EffectStartRefused, match="at least one"):
        begin_effect(spec.id, (), _allowed_decisions(), registry=registry)
    with pytest.raises(EffectStartRefused, match="did not declare"):
        begin_effect(spec.id, [Effect.NETWORK_EGRESS], _allowed_decisions(), registry=registry)
    with pytest.raises(EffectStartRefused, match="missing guard"):
        begin_effect(
            spec.id,
            [Effect.FILESYSTEM_WRITE],
            [GuardDecision("provider.write_policy", True, "path allowed")],
            registry=registry,
        )


def test_central_start_rejects_unknown_and_unimplemented_guard_contracts(monkeypatch) -> None:
    unknown = _central_spec(guard_contracts=("invented.allow",))
    with pytest.raises(EffectStartRefused, match="unknown guard"):
        begin_effect(
            unknown.id,
            [Effect.FILESYSTEM_WRITE],
            [GuardDecision("invented.allow", True, "claim")],
            registry={unknown.id: unknown},
        )

    import daedalus.spine.effect_boundary as boundary

    monkeypatch.setattr(
        boundary,
        "GUARD_CONTRACT_IMPLEMENTED",
        {**dict(boundary.GUARD_CONTRACT_IMPLEMENTED), "test.unimplemented": False},
    )
    monkeypatch.setattr(
        boundary,
        "POLICY_CONTRACTS",
        frozenset(boundary.GUARD_CONTRACT_IMPLEMENTED),
    )
    missing = _central_spec(guard_contracts=("test.unimplemented",))
    with pytest.raises(EffectStartRefused, match="unimplemented guard"):
        begin_effect(
            missing.id,
            [Effect.FILESYSTEM_WRITE],
            [GuardDecision("test.unimplemented", True, "fixture")],
            registry={missing.id: missing},
        )



def test_denial_empty_evidence_duplicate_and_foreign_guard_all_refuse() -> None:
    spec = _central_spec()
    registry = {spec.id: spec}

    denied = list(_allowed_decisions())
    denied[0] = GuardDecision("containment.attempt", False, "sandbox unavailable")
    with pytest.raises(EffectStartRefused, match="denied by containment.attempt"):
        begin_effect(spec.id, [Effect.FILESYSTEM_WRITE], denied, registry=registry)

    empty = list(_allowed_decisions())
    empty[0] = GuardDecision("containment.attempt", True, " ")
    with pytest.raises(EffectStartRefused, match="supplied no evidence"):
        begin_effect(spec.id, [Effect.FILESYSTEM_WRITE], empty, registry=registry)

    duplicate = (*_allowed_decisions(), GuardDecision("containment.attempt", True, "again"))
    with pytest.raises(EffectStartRefused, match="duplicate"):
        begin_effect(spec.id, [Effect.FILESYSTEM_WRITE], duplicate, registry=registry)

    foreign = (*_allowed_decisions(), GuardDecision("budget.process_guard", True, "cap=1"))
    with pytest.raises(EffectStartRefused, match="undeclared guard"):
        begin_effect(spec.id, [Effect.FILESYSTEM_WRITE], foreign, registry=registry)


def test_receipt_is_deterministic_content_addressed_and_immutable() -> None:
    spec = _central_spec()
    registry = {spec.id: spec}
    first = begin_effect(
        spec.id,
        [Effect.PROCESS_SPAWN, Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN],
        _allowed_decisions(),
        registry=registry,
    )
    second = begin_effect(
        spec.id,
        [Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN],
        reversed(_allowed_decisions()),
        registry=registry,
    )

    assert first == second
    assert len(first.receipt_sha256) == 64
    assert first.to_dict()["security_boundary_claimed"] is False
    with pytest.raises(FrozenInstanceError):
        first.entrypoint_id = "rewritten"  # type: ignore[misc]


def test_registry_digest_does_not_depend_on_row_order() -> None:
    rows = (
        _central_spec(id="python.a", target="daedalus.fixture:a"),
        _central_spec(id="python.b", target="daedalus.fixture:b"),
    )
    assert registry_sha256(rows) == registry_sha256(tuple(reversed(rows)))


def test_new_effectful_main_is_a_blocker(tmp_path: Path) -> None:
    root = _minimal_repo(
        tmp_path,
        "import subprocess\n\ndef main():\n    subprocess.run(['tool'])\n",
    )
    report = check_conformance(root, registry=())
    assert any(
        row.code == "entrypoint.unregistered"
        and row.subject == "daedalus.rogue:main"
        and row.severity == "blocker"
        for row in report.findings
    )


@pytest.mark.parametrize(
    "source",
    [
        "from pathlib import Path\n\ndef main():\n    Path('x').write_text('x')\n",
        "def main():\n    open('x', mode='w').write('x')\n",
    ],
)
def test_direct_python_write_forms_are_discovered(tmp_path: Path, source: str) -> None:
    root = _minimal_repo(tmp_path, source)
    rows, findings = discover_entrypoints(root)
    assert not findings
    row = next(item for item in rows if item.target == "daedalus.rogue:main")
    assert Effect.FILESYSTEM_WRITE in row.effects


def test_new_provider_run_is_a_blocker_even_when_sink_is_delegated(tmp_path: Path) -> None:
    root = _minimal_repo(
        tmp_path,
        "from daedalus.providers.base import Provider\n"
        "class SurpriseProvider(Provider):\n"
        "    def run(self):\n"
        "        return delegated_effect()\n",
    )
    report = check_conformance(root, registry=())
    assert any(
        row.code == "entrypoint.unregistered"
        and row.subject == "daedalus.rogue:SurpriseProvider.run"
        for row in report.findings
    )


def test_registered_target_gaining_a_new_effect_is_a_blocker(tmp_path: Path) -> None:
    root = _minimal_repo(
        tmp_path,
        "import subprocess\n\ndef main():\n    subprocess.run(['tool'])\n",
    )
    spec = EntrypointSpec(
        id="cli.rogue",
        surface=Surface.CLI,
        target="daedalus.rogue:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=(),
        wiring=Wiring.INVENTORY_ONLY,
    )
    report = check_conformance(root, registry=(spec,))
    assert any(
        row.code == "entrypoint.effect_drift"
        and "process_spawn" in row.detail
        and row.severity == "blocker"
        for row in report.findings
    )


def test_missing_guard_anchor_is_a_blocker(tmp_path: Path) -> None:
    root = _minimal_repo(
        tmp_path,
        "from pathlib import Path\n\ndef main():\n    Path('x').write_text('x')\n",
    )
    spec = EntrypointSpec(
        id="cli.rogue",
        surface=Surface.CLI,
        target="daedalus.rogue:main",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("provider.write_policy",),
        wiring=Wiring.LOCAL_GUARDS,
        anchors=(GuardAnchor("daedalus.rogue:main", "path_write_blocked"),),
    )
    report = check_conformance(root, registry=(spec,))
    assert any(row.code == "registry.guard_anchor_missing" for row in report.findings)


def test_syntax_error_and_missing_package_fail_closed(tmp_path: Path) -> None:
    broken = _minimal_repo(tmp_path / "broken", "def main(:\n    pass\n")
    broken_report = check_conformance(broken, registry=())
    assert any(row.code == "scan.source_unreadable" for row in broken_report.findings)
    assert broken_report.structurally_conformant is False

    missing = tmp_path / "missing"
    missing.mkdir()
    (missing / "pyproject.toml").write_text("[project]\nname='missing'\n", encoding="utf-8")
    missing_report = check_conformance(missing, registry=())
    assert any(row.code == "scan.package_missing" for row in missing_report.findings)
    assert missing_report.structurally_conformant is False


def test_broken_console_target_fails_closed(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path, "def inspect():\n    return 1\n")
    (root / "pyproject.toml").write_text(
        "[project]\nname='fixture'\n[project.scripts]\nrogue='daedalus.rogue:missing'\n",
        encoding="utf-8",
    )
    _rows, findings = discover_entrypoints(root)
    assert any(row.code == "scan.console_target_missing" for row in findings)


def test_cli_returns_nonzero_and_json_names_real_blockers() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "effect_boundary_check.py"), "--json"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    payload = json.loads(completed.stdout)
    blockers = {
        row["subject"]
        for row in payload["findings"]
        if row["severity"] == "blocker"
    }
    assert completed.returncode == 2
    # Promotion and offload are centrally wired; the CLI remains red for the
    # still-unregistered tool entrypoints, not for either protected Python path.
    assert "python.offload" not in blockers
    assert "python.promote_candidates" not in blockers
    assert any(subject.startswith("tools.") for subject in blockers)
    assert payload["gate0_closed"] is False
    assert payload["security_boundary_claimed"] is False

    # And the scan now reaches tools/. MEASURED 2026-07-30: it globbed
    # root/"daedalus" only, so a newly added effectful entrypoint under tools/
    # changed nothing in the matrix -- verified by adding one. 18 of 19 python
    # files there spawn processes, write files, mutate the repo or spend money,
    # `audit_swarm.py` among them. The registry documents its blind spots
    # (dynamic imports, native code, shell, external clients); this directory
    # was not one of them, and an undocumented gap answers "no drift" for code
    # it never read. Pinned so the scope cannot quietly narrow again.
    subjects = {row["subject"] for row in payload["findings"]}
    assert any(s.startswith("tools.") for s in subjects), (
        "the discovery scan no longer reaches tools/; a whole directory of "
        "effectful entrypoints would be invisible to the drift detector")


def test_promotion_row_is_owner_guarded_before_any_worktree() -> None:
    row = next(item for item in ENTRYPOINTS if item.id == "python.promote_candidates")
    assert row.wiring is Wiring.LOCAL_GUARDS
    assert "promotion.owner_approval" in row.guard_contracts
    assert {anchor.call for anchor in row.anchors} == {
        "authorize_promotion",
        "resolve_live_target_revision",
    }


def test_paid_tools_doors_are_registered_with_spend_and_secrets() -> None:
    """Tier-0 of the effect-boundary inventory: money and keys leave the machine.

    ``tools/guarded_call.py`` is the deliberate external-model door (its only
    sink is a cross-module ``DeepSeekProvider.run`` call the scanner can never
    see), and ``audit_swarm``/``funnel`` are the paid fan-outs. These three and
    the ``provider.deepseek`` lane they ride on must declare ``spend`` and
    ``secrets`` by hand, because section 5 of the inventory measured that no
    static sink can ever infer either effect -- an unregistered or
    under-declared row here stays green while it spends.
    """
    by_id = {row.id: row for row in ENTRYPOINTS}

    for row_id in ("tools.guarded_call", "tools.audit_swarm", "tools.funnel"):
        row = by_id[row_id]
        assert row.surface is Surface.CLI
        assert Effect.SPEND in row.effects, f"{row_id} must declare spend"
        assert Effect.SECRETS in row.effects, f"{row_id} must declare secrets"
        assert Effect.NETWORK_EGRESS in row.effects
        assert "budget.process_guard" in row.guard_contracts
        # inventory_only is the honest wiring: the guards live in callees and
        # no canonical effect start exists yet.  central would be a lie.
        assert row.wiring is Wiring.INVENTORY_ONLY

    # the fan-outs stay anchored to the callee that installs the spend guard
    assert any(a.call == "fan_out" for a in by_id["tools.audit_swarm"].anchors)
    assert any(a.call == "fan_out" for a in by_id["tools.funnel"].anchors)

    deepseek = by_id["provider.deepseek"]
    assert {Effect.SPEND, Effect.SECRETS, Effect.NETWORK_EGRESS} <= set(
        deepseek.effects
    ), "the busiest paid lane must not be declared filesystem_write-only"

    # and the registry rows are live: none of the three tools targets is an
    # unregistered blocker anymore, without silencing the rest of tools/
    report = check_conformance(ROOT)
    unregistered = {
        row.subject
        for row in report.findings
        if row.code == "entrypoint.unregistered" and row.severity == "blocker"
    }
    assert "tools.guarded_call:main" not in unregistered
    assert "tools.audit_swarm:main" not in unregistered
    assert "tools.funnel:main" not in unregistered
