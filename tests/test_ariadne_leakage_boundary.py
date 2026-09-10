"""Master plan section 8.1's self-Renovation leakage boundary is code, not prose.

Before G1-ARIADNE-10 the only target admission an Ariadne campaign performed
was shape plus the mandatory ignored roots (``.git``, ``.daedalus``); a
candidate could have named ``daedalus/spine/...`` or the master plan itself.
The boundary is a pure refusal inside :func:`_admit_target_path`, so it fires
before the repository, HEAD or any effect lease is observed -- the same
discipline the ignored-root refusal already has.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import daedalus.ariadne.campaign as module
from daedalus.ariadne.campaign import (
    SELF_RENOVATION_PROTECTED_PREFIXES,
    AriadneRequestError,
    _admit_target_path,
    protected_prefix_for,
)

REV = "a" * 40

PROTECTED = (
    "daedalus/spine/effect_boundary.py",
    "daedalus/kernel/policy/pricing.py",
    "daedalus/kernel/promotion.py",
    "daedalus/kernel/promotion_trust_root.py",
    "daedalus/kernel/promotion_execution.py",
    "daedalus/kernel/approvals.py",
    "daedalus/kernel/contracts/security.py",
    "daedalus/ariadne/campaign.py",
    "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
    "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl",
    "AGENTS.md",
    "CLAUDE.md",
    ".agentenv/agentenv.json",
    ".agentenv/tool-allowances.json",
    "tests/test_ariadne_campaign_v0.py",
    "tests/test_ariadne_cli_exit_codes.py",
    "tests/test_ariadne_leakage_boundary.py",
    "DAEDALUS/SPINE/ledger.py",
    "Docs/IKARUS_ARIADNE_MASTER_PLAN.md",
    # G1-ARIADNE-13: the boundary covered `campaign.py` and not the code that
    # ENFORCES it. Each of these answered UNPROTECTED before this packet.
    "daedalus/runtimes/computer_ariadne.py",
    "daedalus/runtimes/computer.py",
    "daedalus/orchestration/ikarus/computer_schedule.py",
    "daedalus/kairos/gated_writes.py",
    "daedalus/config.py",
    "tests/kernel/test_sealed_promotion.py",
    "tests/runtimes/test_computer_ariadne.py",
    "tests/test_ikarus_computer_loop_ariadne.py",
    "tests/test_ikarus_computer_schedule_autonomy.py",
)

ADMITTED = (
    "daedalus/providers/codex_cli.py",
    "daedalus/orchestration/ikarus/shell.py",
    "daedalus/ariadne/__init__.py",
    "daedalus/kernel/artifacts.py",
    "docs/STATUS.md",
    "docs/work-packets/G1-SELF-01_DOCSTRING_SYMBOL_DRIFT.md",
    "tests/test_eval.py",
    "README.md",
    # The widening must stay narrow. These are ordinary self-Renovation
    # subjects and a prefix that swallowed them would make the strand useless:
    # `daedalus/runtimes/computer.py` must not take its siblings with it, and
    # `daedalus/config.py` must not take the package.
    "daedalus/runtimes/computer_files.py",
    "daedalus/runtimes/computer_desktop.py",
    "daedalus/runtimes/computer_daedalus.py",
    "daedalus/orchestration/ikarus/computer_loop.py",
    "daedalus/orchestration/loop.py",
    "daedalus/kairos/scheduler.py",
    "daedalus/health.py",
    "tests/test_health_surface.py",
    "tests/runtimes/test_computer_files.py",
)


@pytest.mark.parametrize("target_path", PROTECTED)
def test_protected_target_is_refused_before_read_or_effect(
    tmp_path, monkeypatch, target_path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(
        module,
        "read_repository_source",
        lambda *_args: pytest.fail("protected target reached repository read"),
    )
    monkeypatch.setattr(
        module,
        "acquire_effect_lease",
        lambda *_args, **_kwargs: pytest.fail("protected target reached effect admission"),
    )

    with pytest.raises(AriadneRequestError, match="leakage boundary"):
        module.run_campaign(
            repo_root=root,
            source_revision=REV,
            campaign_id="protected-target",
            target_path=target_path,
            before="before",
            after="after",
        )
    # A refused request leaves no trace: no clone, no receipt, no state.
    assert list(root.iterdir()) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["repo"]


@pytest.mark.parametrize("target_path", PROTECTED)
def test_protected_prefix_is_named_in_the_refusal(target_path) -> None:
    with pytest.raises(AriadneRequestError) as caught:
        _admit_target_path(target_path)
    named = protected_prefix_for(target_path)
    assert named is not None
    assert named in str(caught.value)
    assert named in SELF_RENOVATION_PROTECTED_PREFIXES


@pytest.mark.parametrize("target_path", ADMITTED)
def test_ordinary_source_is_still_admitted(target_path) -> None:
    assert protected_prefix_for(target_path) is None
    assert _admit_target_path(target_path) == target_path


def test_ignored_roots_keep_their_own_refusal_and_precedence() -> None:
    # The ignored-root refusal stays first and keeps its wording.
    with pytest.raises(AriadneRequestError, match="mandatory ignored root"):
        _admit_target_path(".git/HEAD")


def test_the_tuple_covers_every_class_the_plan_names() -> None:
    joined = "\n".join(SELF_RENOVATION_PROTECTED_PREFIXES)
    for needle in (
        "daedalus/spine/",
        "daedalus/kernel/policy/",
        "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
        "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl",
        "AGENTS.md",
        "tests/test_ariadne",
        "daedalus/ariadne/campaign.py",
    ):
        assert needle in joined


#: What each newly protected module HOLDS. The boundary is expressed as paths,
#: so a refactor that moves one of these callables or constants would silently
#: un-protect it while every path test stayed green. Binding the assertion to
#: the symbol makes the move turn this red instead (G1-ARIADNE-13).
LOAD_BEARING = (
    ("daedalus.kairos.gated_writes", "promote_candidates",
     "the callable that promotes a candidate into the checkout"),
    ("daedalus.config", "DEFAULT_WRITE_WAVE_POLICY",
     "the constant that makes the write wave policy 'never' by default"),
    ("daedalus.config", "WRITE_WAVE_POLICY_LEVELS",
     "the closed set that has no level except 'never'"),
    ("daedalus.orchestration.ikarus.computer_schedule", "_repeat_permission",
     "the gate deciding whether a recurring campaign series continues"),
    ("daedalus.runtimes.computer", "ComputerService._admit_release_capability",
     "the fence that admits the campaign tool at all"),
    ("daedalus.ariadne.campaign", "SELF_RENOVATION_PROTECTED_PREFIXES",
     "this boundary itself"),
)


@pytest.mark.parametrize("module_name,symbol,what", LOAD_BEARING)
def test_the_module_defining_each_load_bearing_name_is_protected(
    module_name, symbol, what
) -> None:
    """Ask the interpreter where the name lives, then require that file to be
    behind the boundary.

    Before G1-ARIADNE-13 four of these six answered UNPROTECTED, so a
    self-Renovation candidate could NOMINATE an edit to the callable that
    promotes, to the constant that forbids writing, to the gate that continues
    a series, and to the fence that admits its own tool. Promotion still
    required an owner approval -- this was defence in depth, not a breach --
    but a candidate one approval away from removing its own door is not a
    boundary anyone should rely on while campaigns run unattended."""

    imported = importlib.import_module(module_name)
    holder = imported
    for part in symbol.split("."):
        assert hasattr(holder, part), (
            f"{module_name}.{symbol} moved or was renamed: {what}")
        holder = getattr(holder, part)
    source = Path(imported.__file__).resolve()
    repo_root = Path(module.__file__).resolve().parents[2]
    relative = source.relative_to(repo_root).as_posix()
    named = protected_prefix_for(relative)
    assert named is not None, (
        f"{relative} holds {symbol} ({what}) and is NOT behind the leakage "
        f"boundary. Either add a prefix covering it, or say in the packet why "
        f"a candidate may nominate a change to it.")


def test_the_boundary_covers_its_own_enforcement_not_only_its_definition() -> None:
    """The measurement that produced this packet, kept as a test.

    `daedalus/ariadne/campaign.py` DEFINES the boundary; these enforce it. A
    boundary that protects its definition and not its enforcement protects a
    document."""

    for relative in (
        "daedalus/runtimes/computer_ariadne.py",
        "daedalus/runtimes/computer.py",
        "daedalus/orchestration/ikarus/computer_schedule.py",
        "daedalus/kairos/gated_writes.py",
        "daedalus/config.py",
    ):
        assert protected_prefix_for(relative) is not None, relative
