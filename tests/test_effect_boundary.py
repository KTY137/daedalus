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


def test_inventory_covers_package_and_tools_and_the_scan_reach_stays_pinned() -> None:
    """Both scanned packages are fully inventoried; the reach itself is pinned.

    History, kept because each state was measured: this test first asserted
    completeness while the scan globbed ``root/"daedalus"`` only (true about
    the scope, not the tree -- 18 of 19 python files under tools/ were
    effectful and invisible, MEASURED 2026-07-30).  Then it asserted the
    tools/ gap was non-empty while the 15 unregistered entrypoints were being
    migrated.  Since 2026-08-17 every discovered target in both packages has a
    registry row, so the previous assertion ("unregistered tools rows exist")
    would now re-pin a red state that no longer exists.

    What must never regress silently: the scan still REACHES tools/ -- proven
    by discoveries, not by blockers, because a scan that stopped reading the
    directory would also report zero blockers there.  And structural
    conformance does not mean Gate 0 is closed: the rows are inventory-bound,
    not centrally wired, and the report says so.
    """
    report = check_conformance(ROOT)
    blocker_codes = {(row.code, row.subject) for row in report.findings
                     if row.severity == "blocker"}

    # every discovered entrypoint in both scanned packages is declared
    assert not any(code == "entrypoint.unregistered"
                   for code, _subject in blocker_codes), (
        "an effectful entrypoint fell out of the canonical registry")

    # the scan's reach into tools/ is pinned via what it READ, not via what
    # it flagged -- a silently narrowed scan reports no tools blockers too
    assert any(row.target.startswith("tools.") for row in report.discoveries), (
        "the discovery scan no longer reaches tools/; a whole directory of "
        "effectful entrypoints would be invisible to the drift detector")

    # Promotion and offload keep their mechanically anchored starts.
    assert ("gate0.unguarded_entrypoint", "python.offload") not in blocker_codes
    assert ("gate0.unguarded_entrypoint", "python.promote_candidates") not in blocker_codes
    assert next(row for row in ENTRYPOINTS if row.id == "python.offload").wiring is Wiring.CENTRAL

    # the two hand-registered invisible doors stay named review findings, so
    # their statically unverifiable rows cannot rot without a trace
    review_subjects = {row.subject for row in report.findings
                       if row.code == "entrypoint.not_rediscovered"}
    assert "tools.guarded_call:main" in review_subjects
    assert "tools.system_check:main" in review_subjects

    assert report.structurally_conformant is True
    assert report.gate0_closed is False, (
        "inventory_only rows are a named Gate-0 gap, not conformance")
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


def test_cli_is_conformant_but_still_refuses_to_call_gate0_closed() -> None:
    """The CLI's two failure modes stay distinct and honest.

    Structural conformance (no drift blockers) now passes, so the plain run
    exits 0.  Gate-0 closure is a strictly stronger claim -- every row wired
    through the central start -- and ``--require-gate0`` must keep failing
    with its own exit code while the rows are inventory-bound.  A CLI that
    conflated the two would report a closed gate the moment the registry
    stopped drifting, which is exactly the euphemism the wiring enum exists
    to prevent.
    """
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
    assert completed.returncode == 0
    assert not blockers
    assert payload["structurally_conformant"] is True
    assert payload["gate0_closed"] is False
    assert payload["security_boundary_claimed"] is False

    # Scan reach into tools/ is pinned via discoveries (MEASURED 2026-07-30:
    # the scan once globbed root/"daedalus" only and answered "no drift" for a
    # directory of effectful code it never read).  Blockers cannot pin this
    # anymore -- zero blockers is also what a silently narrowed scan reports.
    discovered = {row["target"] for row in payload["discoveries"]}
    assert any(t.startswith("tools.") for t in discovered), (
        "the discovery scan no longer reaches tools/; a whole directory of "
        "effectful entrypoints would be invisible to the drift detector")

    gated = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "effect_boundary_check.py"),
            "--require-gate0",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert gated.returncode == 3, (
        "--require-gate0 must keep failing while any row is not centrally wired"
    )


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


def test_repo_mutating_tools_declare_repository_mutation_by_hand() -> None:
    """Tier 2 of the inventory: git leaves no statically inferable sink.

    Section 5 measured that ``repository_mutation`` can NEVER enter the
    registry from a discovered sink -- git is argv, not an API call.  So the
    five git-touching tool entrypoints (including the plan guard itself, whose
    source is a protected artifact this registry row inventories without
    touching) must declare it by hand, on top of the fs-write/spawn effects the
    scanner does see; otherwise a row that starts rewriting history stays green
    forever.
    """
    by_id = {row.id: row for row in ENTRYPOINTS}

    for row_id in (
        "tools.iron_plan_guard",
        "tools.gate_discrimination",
        "tools.bootstrap_receipt",
        "tools.operability_drill",
        "tools.gate_host_preflight",
    ):
        row = by_id[row_id]
        assert row.surface is Surface.CLI
        assert Effect.REPOSITORY_MUTATION in row.effects, (
            f"{row_id} touches git; repository_mutation is hand-maintained"
        )
        assert {Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN} <= set(row.effects)
        assert row.wiring is Wiring.INVENTORY_ONLY

    gui = by_id["tools.gui_check"]
    assert {
        Effect.FILESYSTEM_WRITE,
        Effect.NETWORK_EGRESS,
        Effect.PROCESS_CONTROL,
        Effect.PROCESS_SPAWN,
    } <= set(gui.effects)

    report = check_conformance(ROOT)
    unregistered = {
        row.subject
        for row in report.findings
        if row.code == "entrypoint.unregistered" and row.severity == "blocker"
    }
    for target in (
        "tools.iron_plan_guard:main",
        "tools.gate_discrimination:main",
        "tools.bootstrap_receipt:main",
        "tools.operability_drill:main",
        "tools.gate_host_preflight:main",
        "tools.gui_check:main",
    ):
        assert target not in unregistered, target


def test_remaining_tools_rows_and_the_invisible_system_check_are_registered() -> None:
    """Final tools/ batch: write/spawn-only rows plus the dispatch-table door.

    ``tools/system_check.py`` dispatches through its CHECKS table, so no static
    sink resolves and every effect on its row is hand-declared -- including
    repository_mutation (it clones the working tree).  The stale
    ``cli.claude_bridge`` row is gone: its target is a fail-closed stub, and a
    row declaring effects the code cannot perform was the registry's one
    staleness finding.
    """
    by_id = {row.id: row for row in ENTRYPOINTS}

    for row_id, effect in (
        ("tools.mutation_score", Effect.FILESYSTEM_WRITE),
        ("tools.audit_triage", Effect.FILESYSTEM_WRITE),
        ("tools.agent_findings", Effect.FILESYSTEM_WRITE),
        ("tools.lane_invariants", Effect.FILESYSTEM_WRITE),
        ("tools.funnel_report", Effect.PROCESS_SPAWN),
        ("tools.run_gate_checks", Effect.PROCESS_SPAWN),
        ("tools.iron_plan_hook_runner", Effect.PROCESS_SPAWN),
    ):
        row = by_id[row_id]
        assert row.surface is Surface.CLI
        assert effect in row.effects
        assert row.wiring is Wiring.INVENTORY_ONLY

    system_check = by_id["tools.system_check"]
    assert {
        Effect.FILESYSTEM_WRITE,
        Effect.PROCESS_SPAWN,
        Effect.NETWORK_EGRESS,
        Effect.PROCESS_CONTROL,
        Effect.REPOSITORY_MUTATION,
    } <= set(system_check.effects)

    assert "cli.claude_bridge" not in by_id
    assert not any(
        row.target == "daedalus.claude_bridge:main" for row in ENTRYPOINTS
    )


def test_runs_package_is_scanned_and_its_billable_doors_are_registered() -> None:
    """The scan reaches runs/ and its money doors carry hand-declared spend.

    ``runs`` was the one unscanned directory unambiguously in Gate-0 scope:
    ``daedalus.budget.BILLABLE_SITES`` prices five of its functions, yet the
    boundary scan never opened the directory.  The room server additionally
    proves the subclass evasion: it binds through a ``ThreadingHTTPServer``
    subclass the literal-name sink match cannot see, so its ``listen_socket``
    can only exist in the registry by hand -- pinned here so it cannot be
    "simplified" away as undiscoverable.
    """
    from daedalus.spine.effect_boundary import SCAN_PACKAGES

    assert "runs" in SCAN_PACKAGES
    # deliberate, documented exclusions -- widening them requires an explicit
    # harness classification first, not a silent one-line change
    assert "scripts" not in SCAN_PACKAGES
    assert "tests" not in SCAN_PACKAGES

    by_id = {row.id: row for row in ENTRYPOINTS}
    for row_id in ("runs.council.room", "runs.council.summarize", "runs.ab.run_arm"):
        row = by_id[row_id]
        assert Effect.SPEND in row.effects, f"{row_id} is billable and must say so"
        assert "budget.process_guard" in row.guard_contracts
        assert row.wiring is Wiring.INVENTORY_ONLY

    assert Effect.SECRETS in by_id["runs.council.room"].effects
    assert Effect.REPOSITORY_MUTATION in by_id["runs.ab.run_arm"].effects
    assert Effect.LISTEN_SOCKET in by_id["runs.council.room_server"].effects

    report = check_conformance(ROOT)
    assert any(row.target.startswith("runs.") for row in report.discoveries), (
        "the discovery scan no longer reaches runs/")
    assert not any(
        row.code == "entrypoint.unregistered" and row.severity == "blocker"
        for row in report.findings
    ), "widening the scan may not leave unregistered blockers behind"
    # the subclass-evading server stays a named review finding, not silence
    assert "runs.council.room_server:main" in {
        row.subject
        for row in report.findings
        if row.code == "entrypoint.not_rediscovered"
    }
    assert report.structurally_conformant is True
    assert report.gate0_closed is False


def test_harness_entrypoints_are_classified_not_silent_and_never_blockers(
    tmp_path: Path,
) -> None:
    """Tier 5 of the inventory: classify the dev harness, do not migrate it.

    The mutation-run scripts and test fixtures are effectful Python.  Leaving
    them unscanned repeats the measured blind-spot mistake (a scan that never
    reads a directory answers "no drift" for it); promoting them to blockers
    would disable the gate rather than close it.  So the conformance pass
    reads HARNESS_PACKAGES and names every unregistered entrypoint there as an
    ``entrypoint.harness`` REVIEW finding -- counted, inspectable, and out of
    Gate-0 wiring scope by declaration.  This test pins both halves: the
    classification exists, and it can never quietly escalate or degrade
    structural conformance.
    """
    from daedalus.spine.effect_boundary import HARNESS_PACKAGES

    assert HARNESS_PACKAGES == ("scripts", "tests")

    report = check_conformance(ROOT)
    harness = [row for row in report.findings if row.code == "entrypoint.harness"]
    assert harness, "the harness population vanished; the scan stopped reading it"
    assert all(row.severity == "review" for row in harness)
    assert {row.subject.split(".")[0] for row in harness} <= {"scripts", "tests"}
    assert report.structurally_conformant is True

    # mechanism check on a minimal repo: a harness dir gets classified, and
    # the same effectful code inside the production package stays a blocker
    root = _minimal_repo(tmp_path, "def inspect():\n    return 1\n")
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "runner.py").write_text(
        "import subprocess\n\ndef main():\n    subprocess.run(['x'])\n",
        encoding="utf-8",
    )
    fixture_report = check_conformance(root, registry=())
    assert any(
        row.code == "entrypoint.harness"
        and row.subject == "scripts.runner:main"
        and row.severity == "review"
        for row in fixture_report.findings
    )
    assert not any(
        row.code == "entrypoint.unregistered"
        and row.subject.startswith("scripts.")
        for row in fixture_report.findings
    )
