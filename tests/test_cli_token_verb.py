"""`daedalus tokens` is a console door, and it has to actually open.

The monitor was registered on the effect boundary and wired to
``begin_effect`` -- and then had no subcommand, so the only way to reach it was
``python -m daedalus.token_monitor``.  A monitor nobody can invoke from the
product's own CLI is a monitor that gets trusted and never run, which is worse
than not having one: the registry row says the door is guarded, and the door is
not there.

These probes pin the three halves of "wired": the verb dispatches from
``cli.main``'s argv, the registry row is no longer inventory-only, and the
row's guard anchor still resolves against the tree it points at.

MUTATION NOTE: delete the ``elif cmd == "tokens"`` arm in ``daedalus/cli.py``
and the first two tests go red.  Delete the ``begin_effect`` call in
``token_monitor.main`` and the anchor probe goes red (and the family probe in
``tests/test_cli_effect_boundary.py`` goes red with it).  Move that call below
``parse_args`` and the ordering probe goes red.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from daedalus.spine.effect_boundary import (
    ENTRYPOINTS,
    REGISTRY_BY_ID,
    Effect,
    Surface,
    Wiring,
    check_conformance,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_report(tmp_path, monkeypatch):
    """Point every write the verb makes at ``tmp_path``, and cut the log scan.

    The status file, the event journal and the TODO snapshot are module-level
    constants derived from the package location, so there is no environment
    variable to redirect them -- they are monkeypatched here.  The ledger and
    the spine DO take environment variables, and get them, so a test run never
    reads or locks the repository's real money file.

    ``_iter_project_logs`` is stubbed because the real one walks
    ``~/.claude/projects`` and greps every transcript: that is the behaviour
    under test in ``tests/test_hardening.py``, and here it would only make the
    probe slow and machine-dependent.
    """
    import daedalus.memory as memory
    import daedalus.token_monitor as tm

    mem = tmp_path / "memory"
    mem.mkdir()
    monkeypatch.setattr(memory, "MEMORY_DIR", mem)
    monkeypatch.setattr(memory, "EVENTS_PATH", mem / "events.local.jsonl")
    monkeypatch.setattr(memory, "TODO_PATH", mem / "todos.local.md")
    monkeypatch.setattr(tm, "MEMORY_DIR", mem)
    monkeypatch.setattr(tm, "STATUS_PATH", mem / "token_status.local.json")
    monkeypatch.setattr(tm, "_iter_project_logs", lambda repo_root=None: [])
    monkeypatch.setenv(
        "DAEDALUS_BUDGET_LEDGER", str(tmp_path / "budget" / "ledger.json")
    )
    monkeypatch.setenv(
        "DAEDALUS_SPINE_DB", str(tmp_path / "spine" / "spine.sqlite3")
    )
    from daedalus.budget import reset_default_ledger

    reset_default_ledger()
    return mem


def test_the_tokens_verb_is_reachable_from_cli_main_argv(
    tmp_path, monkeypatch, capsys, isolated_report
):
    """The whole chain, driven the way a shell drives it.

    Not a mock of the dispatch: cli.main parses the argv, installs the spend
    guard, imports token_monitor and calls its main, which starts at the
    canonical boundary.  Anything broken anywhere along that chain shows up
    here as an import error, a non-zero exit, or missing JSON.
    """
    from daedalus.cli import main as cli_main

    monkeypatch.setattr(
        "sys.argv",
        ["daedalus", "tokens", "--json", "--repo-root", str(tmp_path / "repo")],
    )
    with pytest.raises(SystemExit) as exit_info:
        cli_main()

    assert exit_info.value.code == 0, (
        "`daedalus tokens` did not exit clean; exit code 2 with no output "
        "usually means the repository's .env was refused before dispatch, "
        "which is a different (and correct) refusal"
    )
    report = json.loads(capsys.readouterr().out)

    # the monitor's own answer
    assert report["summary"]["samples"] == 0
    assert report["triggered"] is False
    # ...and the two stores it READS, present as observations
    assert "budget" in report and "spine" in report
    assert report["budget"]["available"] is True
    assert report["budget"]["spent_usd"] == 0.0
    # the report it wrote landed in the redirected root and nowhere else
    assert (isolated_report / "token_status.local.json").exists()


def test_the_tokens_verb_is_named_in_the_cli_usage():
    """A verb absent from `daedalus --help` is a verb nobody finds.

    Cheap on purpose: the failure it catches is a dispatch arm added without
    the usage line, which leaves the command working and undiscoverable --
    exactly the state this change was made to end.
    """
    usage = (ROOT / "daedalus" / "cli.py").read_text(encoding="utf-8")
    assert "daedalus tokens" in usage


def test_the_registry_row_is_wired_and_claims_no_effect_it_does_not_make():
    row = REGISTRY_BY_ID["cli.token_monitor"]

    assert row.wiring is not Wiring.INVENTORY_ONLY, (
        "an inventory-only row is a row that admits it is not wired"
    )
    assert row.wiring is Wiring.CENTRAL
    assert row.surface is Surface.CLI
    assert row.target == "daedalus.token_monitor:main"
    assert row.guard_contracts == ("budget.process_guard",)
    assert {(anchor.target, anchor.call) for anchor in row.anchors} == {
        ("daedalus.token_monitor:main", "begin_effect")
    }

    # THE DISTINCTION THIS VERB EXISTS TO KEEP. It writes its own report, so
    # FILESYSTEM_WRITE is honest. It reads the money ledger and the intent
    # spine and decides nothing about either, so a SPEND or a REPOSITORY
    # claim here would be a registry row describing a power the code does not
    # have -- and the registry is what a reviewer reads instead of the code.
    assert row.effects == (Effect.FILESYSTEM_WRITE,)
    assert Effect.SPEND not in row.effects
    assert Effect.NETWORK_EGRESS not in row.effects
    assert Effect.REPOSITORY_MUTATION not in row.effects

    # The write roots are not a structured field, so they live in the notes;
    # pin that they are actually named, because "declared somewhere" and
    # "declared nowhere" look identical in a diff.
    for root in ("memory/", "runs/budget/", "runs/spine/"):
        assert root in row.notes, f"write/lock root {root} is not declared"


def test_the_registry_anchor_resolves_against_the_tree():
    """The anchor names a call that exists, in a target that exists.

    Uses the registry's own conformance pass rather than a hand-rolled AST
    walk -- a second implementation of "does this anchor resolve" is a second
    answer to the question, and the one that disagrees is the copy.  Findings
    are filtered to this row so another lane's in-flight registry edit cannot
    turn this probe red.
    """
    row = REGISTRY_BY_ID["cli.token_monitor"]
    report = check_conformance(ROOT, registry=(row,))
    anchor_codes = {
        "registry.anchor_target_missing",
        "registry.guard_anchor_missing",
        "registry.target_missing",
    }
    broken = [
        finding
        for finding in report.findings
        if finding.code in anchor_codes and finding.subject == row.id
    ]
    assert broken == [], f"the cli.token_monitor anchor no longer resolves: {broken}"


def test_the_row_is_the_only_owner_of_its_target():
    """One target, one registry owner -- so adding the verb did not add a row."""
    owners = [
        row for row in ENTRYPOINTS if row.target == "daedalus.token_monitor:main"
    ]
    assert len(owners) == 1, f"daedalus.token_monitor:main has {len(owners)} owners"


def test_the_boundary_start_precedes_argument_parsing_in_the_source():
    """Ordering no single runtime trace can prove for every future code path.

    ``begin_effect`` sitting above ``parse_args`` is what makes the start
    unconditional: no ``--help``, no parse error and no future branch of
    ``main`` can reach the status write around it.  Before this change the
    call sat *after* ``parse_args`` and after ``resolve_repo_root``, so the
    ordering was a property of the current code rather than of the function.
    """
    module = ast.parse(
        (ROOT / "daedalus" / "token_monitor.py").read_text(encoding="utf-8")
    )
    main = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    lines: dict[str, int] = {}
    for node in ast.walk(main):
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            )
            if name and name not in lines:
                lines[name] = node.lineno

    assert "begin_effect" in lines
    assert "process_guard_boundary_decision" in lines
    assert "parse_args" in lines
    assert lines["begin_effect"] < lines["parse_args"]
    assert lines["process_guard_boundary_decision"] < lines["parse_args"]
