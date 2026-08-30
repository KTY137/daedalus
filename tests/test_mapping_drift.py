# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Fixtures for every classification the architecture-drift gate can emit,
plus the properties the gate lives or dies on: it consumes ONE analysis, an
acceptance suppresses, an acceptance that outlived its reason comes back, and
none of the seven measured bypasses works any more.

Every fixture is a real (tiny) source tree. Nothing here touches the network, a
model, a vendor CLI or the developer's own snapshot.

Read the BYPASSES section as the specification: each test there corresponds to
a way the gate was measured to return green while hiding a real finding, and
each one fails if its fix is reverted.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from daedalus.mapping import drift

TODAY = date(2026, 7, 28)


# ---------------------------------------------------------------- fixtures

def mk(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


BASE = {
    "pyproject.toml": '[project]\nname = "pkg"\n\n[project.scripts]\npkg = "pkg.cli:main"\n',
    # __init__ is reached as a package parent of everything below it.
    "pkg/__init__.py": "from pkg import wired\n",
    "pkg/wired.py": "from pkg import deep\nVALUE = 1\n",
    "pkg/deep.py": "VALUE = 2\n",
    # reached ONLY through the console-script entrypoint -- the case a naive
    # "fan_in == 0" island rule gets wrong.
    "pkg/cli.py": "from pkg import clionly\n\n\ndef main():\n    return 0\n",
    "pkg/clionly.py": "X = 1\n",
    "tests/test_main.py": "from pkg import wired\n",
}


def check(root: Path, snap: Path, **kw):
    kw.setdefault("today", TODAY)
    return drift.check(root, snap, **kw)


def scan(root: Path):
    return drift.scan(root).state


def read(snap: Path) -> dict:
    return json.loads(snap.read_text(encoding="utf-8"))


def write(snap: Path, doc: dict) -> None:
    snap.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def edit_signed(snap: Path, **changes) -> None:
    """Hand-edit AND re-sign, so a test can isolate a coherence rule from the
    digest that would otherwise catch the edit first."""
    doc = read(snap)
    doc.update(changes)
    doc[drift.DIGEST_KEY] = drift._digest(doc)
    write(snap, doc)


def kinds(report) -> list[str]:
    return [i.kind for i in report.items]


def item(report, kind, key=None):
    for i in report.items:
        if i.kind == kind and (key is None or i.key == key):
            return i
    raise AssertionError(
        f"no {kind}{'/' + key if key else ''} in {[(i.kind, i.key) for i in report.items]}")


def accept(snap: Path, key: str, *, since="2026-07-20", until="2026-08-20",
           why="the CLI wiring lands in the follow-up commit", who="kaya"):
    doc = read(snap)
    doc.setdefault("acceptances", []).append(
        {"item": key, "why": why, "since": since, "until": until, "who": who})
    write(snap, doc)


@pytest.fixture()
def repo(tmp_path):
    return mk(tmp_path / "repo", dict(BASE))


@pytest.fixture()
def snap(tmp_path):
    return tmp_path / "docs" / "architecture-state.json"


@pytest.fixture()
def based(repo, snap):
    """A repo with its baseline already recorded and clean."""
    report = check(repo, snap, write_missing=True)
    assert report.first_run and report.ok and report.wrote_snapshot
    return repo, snap


# ---------------------------------------------------------------- first run

def test_a_missing_snapshot_fails_and_writes_nothing(repo, snap):
    """M3. ``rm docs/architecture-state.json`` must not be a green run.

    The gate used to treat a missing snapshot as a clean FIRST RUN, write the
    baseline including whatever was wrong, and exit 0 -- through a door
    reach.py itself classifies as an entry point."""
    assert not snap.exists()
    report = check(repo, snap)

    assert report.ok is False
    assert report.first_run is True
    assert report.wrote_snapshot is False
    assert not snap.exists()
    text = report.render()
    assert "NO BASELINE" in text
    assert "NOTHING WAS COMPARED" in text
    assert "--init" in text


def test_recording_a_baseline_is_an_explicit_action(repo, snap):
    report = check(repo, snap, write_missing=True)
    assert report.ok is True and report.first_run and report.wrote_snapshot
    assert snap.exists(), "the parent directory must be created too"

    recorded = read(snap)
    assert recorded["islands"] == []      # BASE has no islands
    assert recorded["acceptances"] == []
    assert recorded["counts"]["modules"] == 5   # the tests/ tree is not cargo
    assert "FIRST RUN" in report.render()


def test_module_entry_point_fails_closed_on_a_missing_snapshot(repo, snap, capsys):
    """M3, at the entry point a human actually takes."""
    rc = drift.main(["--repo", str(repo), "--snapshot", str(snap)])
    out = capsys.readouterr().out
    assert rc == 1
    assert not snap.exists()
    assert "NO BASELINE" in out


def test_init_writes_the_baseline_and_refuses_to_overwrite(repo, snap, capsys):
    assert drift.main(["--repo", str(repo), "--snapshot", str(snap), "--init"]) == 0
    capsys.readouterr()
    assert snap.exists()
    assert drift.main(["--repo", str(repo), "--snapshot", str(snap), "--init"]) == 1
    assert "already exists" in capsys.readouterr().out


def test_second_run_over_an_unchanged_tree_is_clean(based):
    repo, snap = based
    report = check(repo, snap)
    assert report.ok
    assert report.items == []
    assert "no drift against the snapshot" in report.render()


# ------------------------------------------------- ONE ENGINE (the root fix)

def test_gate_islands_are_exactly_reach_islands_plus_orphans(based):
    """H5. The gate used to run its own reachability scan. On the real tree the
    two lists shared ONE member out of sixteen; the page then printed prose
    reconciling the gap with a reason that predicted the wrong direction.

    The gate's list is now a function of reach's classification: island plus
    orphan, nothing added and nothing dropped."""
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n",
              "pkg/shim.py": "from pkg.deep import VALUE\n\n__all__ = ['VALUE']\n"})

    from daedalus.mapping import reach as reach_mod
    rep = reach_mod.analyse(repo)
    # the literal, not drift.ISLAND_CLASSES: a test that reads the constant it
    # is checking cannot fail when the constant moves
    expected = sorted(m.module for m in rep.modules
                      if m.classification in ("island", "orphan"))
    assert drift.ISLAND_CLASSES == ("island", "orphan")

    state = scan(repo)
    assert state["islands"] == expected
    assert expected, "the fixture has to actually contain one"
    # and the shim is NOT in it: reach gives it its own class, and a re-export
    # that nothing names is expected rather than alarming
    assert "pkg/shim.py" not in state["islands"]


# ------------------------------------------- BYPASS: the dropped reach classes
#
# CONFIGURATION for this whole block: ``drift.check(root, snap)`` -- the gate's
# own entry point, the same call `daedalus map --check` makes. No index is
# supplied here on purpose; the index-dependent half of the same bug lives in
# tests/test_mapping_reach.py and tests/test_mapping_cli.py, and these four
# routes are ones the gate misses with or without one.

def test_every_reach_class_is_either_reached_or_counted_as_unreached(based):
    """The rule that would have caught this whole class of bug at design time.

    reach can emit seven classes. The gate had a list of two, and the other two
    that mean "nothing reaches it" -- ``unknown`` and ``shim`` -- appeared in no
    list, no count and no kind. Every class reach can emit must land on exactly
    one side of this partition, so a new one cannot be dropped silently."""
    from daedalus.mapping.reach import CLASSES
    assert set(drift.UNREACHED_CLASSES) | set(drift.REACHED_CLASSES) == set(CLASSES)
    assert not set(drift.UNREACHED_CLASSES) & set(drift.REACHED_CLASSES)
    assert set(drift.ISLAND_CLASSES) < set(drift.UNREACHED_CLASSES), (
        "islands is a SUBSET of unreached -- reporting only it is the bug")


def test_a_module_imported_only_under_if_false_blocks_the_gate(based):
    """Route 1 of four measured EXIT-0 routes. ``if False: from pkg import
    secret`` makes reach say ``unknown``; ``unknown`` was in no gate list, so a
    genuinely unwired module on disk produced a clean run."""
    repo, snap = based
    mk(repo, {"pkg/secret.py": "VALUE = 9\n",
              "pkg/cli.py": ("from pkg import clionly\n\nif False:\n"
                             "    from pkg import secret\n\n\ndef main():\n"
                             "    return 0\n")})

    state = scan(repo)
    assert state["unknown"] == ["pkg/secret.py"]
    assert state["counts"]["unreached"] == state["counts"]["islands"] + 1

    report = check(repo, snap)
    assert report.ok is False
    found = item(report, drift.NEW_UNKNOWN, "unknown:pkg/secret.py")
    assert found.blocking is True
    assert "NEW UNKNOWN (1)" in report.render()
    assert "pkg/secret.py" in report.render()


def test_a_module_imported_only_under_a_swallowed_importerror_blocks(based):
    """Route 2."""
    repo, snap = based
    mk(repo, {"pkg/secret.py": "VALUE = 9\n",
              "pkg/cli.py": ("from pkg import clionly\n\ntry:\n"
                             "    from pkg import secret\n"
                             "except ImportError:\n    secret = None\n\n\n"
                             "def main():\n    return 0\n")})
    report = check(repo, snap)
    assert report.ok is False
    assert item(report, drift.NEW_UNKNOWN, "unknown:pkg/secret.py").blocking


def test_a_module_named_only_by_a_string_literal_blocks(based):
    """Route 3: ``NOTE = 'pkg.secret'`` in any non-test module. reach refuses to
    call it an island -- correctly, it cannot prove either way -- and the gate
    then refused to mention it at all."""
    repo, snap = based
    mk(repo, {"pkg/secret.py": "VALUE = 9\n",
              "pkg/wired.py": "from pkg import deep\nNOTE = 'pkg.secret'\n"})
    report = check(repo, snap)
    assert report.ok is False
    found = item(report, drift.NEW_UNKNOWN, "unknown:pkg/secret.py")
    assert "will not guess" in found.remedy


def test_a_new_re_export_shim_nothing_reaches_blocks(based):
    """Route 4: a module that only re-exports gets reach's ``shim`` class, which
    was also in no gate list. A shim IS deliberate -- which is why it gets its
    own kind and its own remedy rather than being called an island -- but a
    forward nothing reaches is still a module nobody can get to."""
    repo, snap = based
    mk(repo, {"pkg/oldname.py": "from pkg.deep import VALUE\n\n__all__ = ['VALUE']\n"})

    state = scan(repo)
    assert state["shims"] == ["pkg/oldname.py"]
    assert state["islands"] == [], "a shim is NOT an island; the remedies differ"

    report = check(repo, snap)
    assert report.ok is False
    found = item(report, drift.NEW_SHIM, "shim:pkg/oldname.py")
    assert found.blocking is True
    assert "delete the forward" in found.remedy
    assert "NEW UNREACHED SHIM (1)" in report.render()


def test_the_unreached_total_is_the_sum_of_the_three_lists(based):
    """The arithmetic the page has to add up to. ``islands`` is one third of the
    answer, and printing it alone is what hid the other two thirds."""
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n",
              "pkg/oldname.py": "from pkg.deep import VALUE\n\n__all__ = ['VALUE']\n",
              "pkg/secret.py": "VALUE = 9\n",
              "pkg/wired.py": "from pkg import deep\nNOTE = 'pkg.secret'\n"})
    state = scan(repo)
    assert state["islands"] == ["pkg/orphan.py"]
    assert state["unknown"] == ["pkg/secret.py"]
    assert state["shims"] == ["pkg/oldname.py"]
    assert state["counts"]["unreached"] == 3
    assert state["counts"]["unreached"] == (
        state["counts"]["islands"] + state["counts"]["unknown"]
        + state["counts"]["shims"])

    from daedalus.mapping import reach as reach_mod
    rep = reach_mod.analyse(repo)
    honest = [m.module for m in rep.modules
              if m.classification in ("island", "orphan", "unknown", "shim")]
    assert sorted(state["islands"] + state["unknown"] + state["shims"]) \
        == sorted(honest)


def test_this_repository_counts_every_unreached_module(based):
    """Self-application, as a property rather than a magic number: on the real
    tree the three lists together must equal reach's own unreached set. When
    this was written the gate said islands=7 and the honest total was 10 --
    three real shims (decompose.py, drafts.py, mission_control.py) that nothing
    reaches and nothing tests."""
    root = Path(__file__).resolve().parents[1]
    from daedalus.mapping import reach as reach_mod
    rep = reach_mod.analyse(root)
    state = drift.scan(root, reach_report=rep).state
    honest = sorted(m.module for m in rep.modules
                    if m.classification in drift.UNREACHED_CLASSES)
    assert sorted(state["islands"] + state["unknown"] + state["shims"]) == honest
    assert state["counts"]["unreached"] == len(honest)
    assert state["counts"]["unreached"] > state["counts"]["islands"], (
        "this repo has unreached modules that are not islands -- if that ever "
        "stops being true, keep the property and drop this line")


def test_an_unknown_and_a_shim_are_acceptable_with_a_date(based):
    """Both block, so both must have a Tier-1 path -- a gate that cannot be
    satisfied is bypassed within a week."""
    repo, snap = based
    mk(repo, {"pkg/oldname.py": "from pkg.deep import VALUE\n\n__all__ = ['VALUE']\n",
              "pkg/secret.py": "VALUE = 9\n",
              "pkg/wired.py": "from pkg import deep\nNOTE = 'pkg.secret'\n"})
    accept(snap, "shim:pkg/oldname.py", why="the callers move in the next commit")
    accept(snap, "unknown:pkg/secret.py", why="loaded by the plugin registry")
    report = check(repo, snap)
    assert report.ok is True
    assert item(report, drift.NEW_SHIM, "shim:pkg/oldname.py").accepted
    assert item(report, drift.NEW_UNKNOWN, "unknown:pkg/secret.py").accepted


def test_an_unreached_module_reached_only_by_its_test_is_test_only(based):
    """TEST ONLY is a property of an unreached module, not of an island. It was
    scoped to islands, so a shim or an unknown whose only importer is a test
    could not be described that way at all."""
    repo, snap = based
    mk(repo, {"pkg/oldname.py": "from pkg.deep import VALUE\n\n__all__ = ['VALUE']\n",
              "tests/test_oldname.py": "from pkg import oldname\n"})
    report = check(repo, snap)
    assert report.state["test_only"] == ["pkg/oldname.py"]
    found = item(report, drift.TEST_ONLY, "test-only:pkg/oldname.py")
    assert found.blocking is False
    assert report.ok is True
    assert drift.NEW_SHIM not in kinds(report)


def test_moving_between_unreached_classes_is_not_good_news(based):
    """An island that becomes a shim is still reached by nothing. Announcing
    NOW REACHED for it would be the same false-green wearing a new class."""
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    drift.refresh(repo, snap)
    assert read(snap)["islands"] == ["pkg/orphan.py"]

    mk(repo, {"pkg/orphan.py": "from pkg.deep import VALUE\n\n__all__ = ['VALUE']\n"})
    report = check(repo, snap)
    assert drift.NOW_REACHED not in kinds(report)
    assert item(report, drift.NEW_SHIM, "shim:pkg/orphan.py").blocking
    assert report.ok is False


def test_an_unknown_that_gets_wired_is_now_reached(based):
    """The good-news direction has to work for the new lists too, or an
    acceptance on one can never go stale."""
    repo, snap = based
    mk(repo, {"pkg/secret.py": "VALUE = 9\n",
              "pkg/wired.py": "from pkg import deep\nNOTE = 'pkg.secret'\n"})
    drift.refresh(repo, snap)
    assert read(snap)["unknown"] == ["pkg/secret.py"]

    mk(repo, {"pkg/wired.py": "from pkg import deep\nfrom pkg import secret\n"})
    report = check(repo, snap)
    found = item(report, drift.NOW_REACHED, "unknown:pkg/secret.py")
    assert found.blocking is False
    assert report.ok is True


def test_pre_seeding_the_new_lists_is_an_invalid_snapshot(based):
    """The coherence rule has to cover the new lists too, or ``unknown`` becomes
    the cheapest place to hide a module."""
    repo, snap = based
    edit_signed(snap, unknown=["pkg/ghost.py"],
                counts=dict(read(snap)["counts"], unknown=1, unreached=1))
    report = check(repo, snap)
    assert report.ok is False
    bad = item(report, drift.INVALID_SNAPSHOT, "snapshot:unknown.not-a-module")
    assert "pkg/ghost.py" in bad.detail


def test_the_unreached_count_must_match_its_own_lists(based):
    repo, snap = based
    edit_signed(snap, counts=dict(read(snap)["counts"], unreached=99))
    report = check(repo, snap)
    assert report.ok is False
    bad = item(report, drift.INVALID_SNAPSHOT, "snapshot:counts.unreached")
    assert "snapshot says 99" in bad.detail


# -------------------------------------- BYPASS: the two engines disagreeing

def test_an_edge_only_the_structural_index_has_is_a_finding(based):
    """reach REPORTS index-only edges and refuses to merge them (that refusal is
    CRITICAL 1). This is the other half: a disagreement that persists has to
    become somebody's problem rather than a line nobody reads.

    CONFIGURATION: ``drift.check(..., index=...)``, which is how both
    ``daedalus map`` and ``python -m daedalus.mapping.drift`` call it -- both
    build a structcore index and forward it."""
    repo, snap = based
    fake_index = {"import_edges": {"pkg/deep.py": ["pkg/cli.py"]}}
    report = check(repo, snap, index=fake_index)
    assert report.ok is False
    found = item(report, drift.ENGINE_DISAGREEMENT, "index-edge:pkg/deep.py -> pkg/cli.py")
    assert found.blocking is True
    assert "never merged" in found.detail
    assert report.state["index_extra_edges"] == ["pkg/deep.py -> pkg/cli.py"]


def test_an_agreeing_index_produces_no_disagreement(based):
    repo, snap = based
    report = check(repo, snap, index={"import_edges": {"pkg/wired.py": ["pkg/deep.py"]}})
    assert drift.ENGINE_DISAGREEMENT not in kinds(report)
    assert report.ok is True


def test_gate_dark_switches_are_switches_dark_minus_documented_and_secrets(based):
    """H5, the other half. The gate reported 0 dark switches on a repo where
    the switch engine reported 15 -- the dark half had never fired."""
    repo, snap = based
    mk(repo, {"pkg/wired.py": (
        "import os\n"
        "from pkg import deep\n"
        "\n"
        "\n"
        "def turbo():\n"
        "    if os.environ.get('PKG_TURBO'):\n"
        "        return deep.VALUE\n"
        "    if os.environ.get('PKG_API_KEY'):\n"
        "        return 1\n"
        "    return 0\n"),
        "docs/flags.md": "Set `PKG_LOUD=1` to print every routing decision.\n"})
    mk(repo, {"pkg/deep.py": (
        "import os\n"
        "VALUE = 2\n"
        "if os.environ.get('PKG_LOUD'):\n"
        "    VALUE = 3\n")})

    from daedalus.mapping import switches as switches_mod
    sw = switches_mod.analyse(repo)
    engine_dark = {s.name for s in sw.env_switches if s.dark}
    assert {"PKG_TURBO", "PKG_LOUD", "PKG_API_KEY"} <= engine_dark

    state = scan(repo)
    docs = drift.DocIndex.build(repo)
    expected = sorted(
        s.name for s in sw.env_switches
        if s.dark and s.kind != "secret" and not docs.documents(s.name))
    assert state["dark_switches"] == expected
    assert state["dark_switches"] == ["PKG_TURBO"], (
        "PKG_LOUD is documented, PKG_API_KEY is a credential")


def test_the_two_engines_are_only_run_once_when_they_are_supplied(based):
    """The plumbing that makes 'one answer' true rather than merely likely."""
    repo, snap = based
    from daedalus.mapping import reach as reach_mod, switches as switches_mod
    rep = reach_mod.analyse(repo)
    sw = switches_mod.analyse(repo)
    result = drift.scan(repo, reach_report=rep, switch_report=sw)
    assert result.reach is rep
    assert result.switches is sw
    assert result.state == scan(repo)


# ------------------------------------------------------- the classifications

def test_new_island(based):
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})

    report = check(repo, snap)
    assert not report.ok
    found = item(report, drift.NEW_ISLAND, "island:pkg/orphan.py")
    assert found.blocking
    assert "nothing reaches it" in found.detail
    assert "wire it" in found.remedy


def test_module_reached_only_through_a_console_script_is_not_an_island(repo):
    """The reason reachability is a closure from entry points and not
    ``fan_in > 0``: nothing imports ``pkg/cli.py``, so a fan-in rule would call
    both it and everything it pulls in an island."""
    state = scan(repo)
    assert state["islands"] == []
    assert "pkg/clionly.py" in state["modules"]


def test_became_island(based):
    repo, snap = based
    # pkg/deep.py had exactly one caller and it just lost it
    mk(repo, {"pkg/wired.py": "VALUE = 1\n"})

    report = check(repo, snap)
    assert not report.ok
    found = item(report, drift.BECAME_ISLAND, "island:pkg/deep.py")
    assert "was reachable in the snapshot" in found.detail
    assert "deleted or renamed" in found.remedy
    assert "island:pkg/wired.py" not in [i.key for i in report.items]
    assert drift.NEW_ISLAND not in kinds(report)


def test_now_reached_is_reported_and_never_blocks(repo, snap):
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    check(repo, snap, write_missing=True)               # baseline WITH the island
    assert "pkg/orphan.py" in read(snap)["islands"]

    mk(repo, {"pkg/__init__.py": "from pkg import wired\nfrom pkg import orphan\n"})
    report = check(repo, snap)

    found = item(report, drift.NOW_REACHED, "island:pkg/orphan.py")
    assert found.blocking is False
    assert report.ok is True, "good news must not fail the gate"
    assert "NOW REACHED" in report.render()


def test_vanished(based):
    repo, snap = based
    (repo / "pkg" / "deep.py").unlink()
    mk(repo, {"pkg/wired.py": "VALUE = 1\n"})

    report = check(repo, snap)
    assert not report.ok
    found = item(report, drift.VANISHED, "vanished:pkg/deep.py")
    assert "not on disk" in found.detail
    assert not any(i.key == "island:pkg/deep.py" for i in report.items)


def test_new_dark_switch(based):
    repo, snap = based
    mk(repo, {"pkg/wired.py": (
        "import os\n"
        "from pkg import deep\n"
        "\n"
        "\n"
        "def turbo():\n"
        "    if os.environ.get('PKG_TURBO'):\n"
        "        return deep.VALUE\n"
        "    return 0\n")})

    report = check(repo, snap)
    assert not report.ok
    found = item(report, drift.NEW_DARK_SWITCH, "dark-switch:PKG_TURBO")
    assert "pkg/wired.py:6" in found.detail
    assert "document PKG_TURBO" in found.remedy


def test_on_by_default_gate_is_not_dark(based):
    repo, snap = based
    mk(repo, {"pkg/wired.py": ("import os\nfrom pkg import deep\n"
                               "ON = os.environ.get('PKG_SAFE', '1') != '0'\n")})
    report = check(repo, snap)
    assert drift.NEW_DARK_SWITCH not in kinds(report)


def test_credentials_and_platform_vars_are_not_dark_switches(based):
    repo, snap = based
    mk(repo, {"pkg/wired.py": (
        "import os\n"
        "from pkg import deep\n"
        "\n"
        "CONFIGURED = bool(os.environ.get('PKG_API_KEY'))\n"
        "HAS_HOME = bool(os.environ.get('LOCALAPPDATA'))\n")})

    report = check(repo, snap)
    assert drift.NEW_DARK_SWITCH not in kinds(report)
    keys = [i.key for i in report.items]
    assert "doc-drift:code-only:LOCALAPPDATA" not in keys, (
        "platform vars are not this project's to document")
    assert "doc-drift:code-only:PKG_API_KEY" in keys


def test_doc_drift_both_directions(based):
    repo, snap = based
    mk(repo, {
        "pkg/wired.py": ("import os\nfrom pkg import deep\n"
                         "LEVEL = os.environ.get('PKG_LEVEL', 'high')\n"),
        "docs/config.md": "Set `PKG_GHOST` to rebalance the flux.\n",
    })

    report = check(repo, snap)
    assert not report.ok
    code_only = item(report, drift.DOC_DRIFT, "doc-drift:code-only:PKG_LEVEL")
    assert "no document mentions it" in code_only.detail
    doc_only = item(report, drift.DOC_DRIFT, "doc-drift:doc-only:PKG_GHOST")
    assert "no code reads it any more" in doc_only.detail


def test_doc_prose_is_not_mined_for_unrelated_shouting(based):
    repo, snap = based
    mk(repo, {"docs/notes.md": (
        "IMPORTANT: see MISSION_CONTROL and ENGINE_PARITY. MAX_RETRY_COUNT "
        "is a constant, DB_PASSWORD belongs to the server.\n")})
    report = check(repo, snap)
    assert drift.DOC_DRIFT not in kinds(report)


# ------------------------------------------------------------- BYPASS: C1

def test_an_acceptance_dated_in_the_future_is_invalid(based):
    """C1. ``{"since": "2999-01-01", "until": "2999-03-01"}`` is a 59-day
    horizon, so the cap alone accepted it -- and it then suppressed the finding
    today, and in ten years, permanently. The horizon has to bind to the
    calendar, not only to itself."""
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    accept(snap, "island:pkg/orphan.py", since="2999-01-01", until="2999-03-01")

    for when in (TODAY, date(2036, 7, 28)):
        report = check(repo, snap, today=when)
        assert report.ok is False, f"still suppressed at {when}"
        bad = item(report, drift.INVALID_ACCEPTANCE,
                   "acceptance:island:pkg/orphan.py")
        assert "future" in bad.detail
        still = item(report, drift.NEW_ISLAND, "island:pkg/orphan.py")
        assert still.blocking is True
        assert still.accepted is False


def test_an_acceptance_starting_tomorrow_is_invalid(based):
    """The boundary: today is fine, today+1 is not."""
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    accept(snap, "island:pkg/orphan.py", since="2026-07-28", until="2026-08-20")
    assert check(repo, snap, today=date(2026, 7, 28)).ok is True
    assert check(repo, snap, today=date(2026, 7, 27)).ok is False


def test_the_render_teaches_the_rule_it_enforces(based):
    """The remedy block is the documented Tier-1 path. When it taught only the
    horizon cap, it was teaching the rule that was being evaded."""
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    text = check(repo, snap).render()
    assert "'since' may not be in the future" in text
    assert f"at most {drift.MAX_HORIZON_DAYS} days" in text


# ------------------------------------------------------------- BYPASS: H1

def test_pre_seeding_the_snapshot_breaks_the_digest(based):
    """H1. The third undated way to accept: hand-add the item to ``islands``,
    bump ``counts``, done -- no INVALID SNAPSHOT, no VANISHED, ok=True.

    Every mechanical list is covered by a digest, so a text editor cannot do
    it any more. Re-running Python to re-sign is not the same thing: the
    control on a deliberate re-baseline is the reviewed diff, which is Tier 2
    and works exactly as designed."""
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    doc = read(snap)
    doc["modules"] = sorted(doc["modules"] + ["pkg/orphan.py"])
    doc["islands"] = ["pkg/orphan.py"]
    doc["counts"]["modules"] = len(doc["modules"])
    doc["counts"]["islands"] = 1
    write(snap, doc)

    report = check(repo, snap)
    assert report.ok is False
    bad = item(report, drift.INVALID_SNAPSHOT, "snapshot:digest")
    assert "hand-edited" in bad.detail


def test_an_island_that_is_not_a_module_is_an_invalid_snapshot(based):
    """H1, with the digest re-signed so the coherence rule is what is tested."""
    repo, snap = based
    edit_signed(snap, islands=["pkg/ghost.py"],
                counts=dict(read(snap)["counts"], islands=1))

    report = check(repo, snap)
    assert report.ok is False
    bad = item(report, drift.INVALID_SNAPSHOT, "snapshot:islands.not-a-module")
    assert "pkg/ghost.py" in bad.detail


def test_a_dark_switch_no_module_reads_is_an_invalid_snapshot(based):
    """H1's other half: a switch cannot be baselined before the code that
    reads it lands, or the NEW DARK SWITCH for it never fires."""
    repo, snap = based
    edit_signed(snap, dark_switches=["PKG_EXPERIMENTAL_MODE"],
                counts=dict(read(snap)["counts"], dark_switches=1))

    report = check(repo, snap)
    assert report.ok is False
    bad = item(report, drift.INVALID_SNAPSHOT, "snapshot:dark_switches.unread")
    assert "PKG_EXPERIMENTAL_MODE" in bad.detail


def test_a_pre_seeded_island_still_reports_when_the_module_is_not_baselined(based):
    """The teeth behind the subset rule: an island entry whose module the
    snapshot does not know about must not suppress the finding either."""
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    edit_signed(snap, islands=["pkg/orphan.py"],
                counts=dict(read(snap)["counts"], islands=1))

    report = check(repo, snap)
    assert report.ok is False
    item(report, drift.INVALID_SNAPSHOT, "snapshot:islands.not-a-module")
    still = item(report, drift.NEW_ISLAND, "island:pkg/orphan.py")
    assert still.blocking is True


def test_a_test_only_entry_that_is_not_an_island_is_an_invalid_snapshot(based):
    """The third coherence rule: every test-only module is an island first, so
    ``test_only`` cannot be used to smuggle a module past the island list."""
    repo, snap = based
    edit_signed(snap, test_only=["pkg/wired.py"],
                counts=dict(read(snap)["counts"], test_only=1))

    report = check(repo, snap)
    assert report.ok is False
    bad = item(report, drift.INVALID_SNAPSHOT, "snapshot:test_only.not-an-island")
    assert "pkg/wired.py" in bad.detail


def test_a_schema_from_a_different_engine_is_refused(based):
    repo, snap = based
    edit_signed(snap, schema=1)
    report = check(repo, snap)
    assert report.ok is False
    item(report, drift.INVALID_SNAPSHOT, "snapshot:schema")


# ------------------------------------------------------------- BYPASS: H2

DARK_MODULE = ("import os\nfrom pkg import deep\n"
               "\n"
               "\n"
               "def go():\n"
               "    if os.environ.get('PKG_EXPERIMENTAL_MODE'):\n"
               "        return deep.VALUE\n"
               "    return 0\n")


def test_a_bare_token_in_a_markdown_file_does_not_document_a_switch(based):
    """H2. One word in ``docs/notes.md`` moved the gate from dark=1, FAILED to
    dark=0, OK with no trace at all. "Documented" was a whole-token regex over
    every markdown file in the tree."""
    repo, snap = based
    mk(repo, {"pkg/wired.py": DARK_MODULE})
    assert item(check(repo, snap), drift.NEW_DARK_SWITCH,
                "dark-switch:PKG_EXPERIMENTAL_MODE").blocking

    mk(repo, {"docs/notes.md": "PKG_EXPERIMENTAL_MODE\n"})
    report = check(repo, snap)
    assert report.ok is False
    assert item(report, drift.NEW_DARK_SWITCH,
                "dark-switch:PKG_EXPERIMENTAL_MODE").blocking


def test_a_named_switch_without_an_explanation_does_not_count(based):
    repo, snap = based
    mk(repo, {"pkg/wired.py": DARK_MODULE,
              "docs/notes.md": "`PKG_EXPERIMENTAL_MODE` is a flag.\n"})
    assert item(check(repo, snap), drift.NEW_DARK_SWITCH,
                "dark-switch:PKG_EXPERIMENTAL_MODE").blocking


def test_a_mention_inside_a_code_fence_does_not_count(based):
    """A fenced sample is exactly where a name appears without being
    explained, and it is the easiest place to drop one."""
    repo, snap = based
    mk(repo, {"pkg/wired.py": DARK_MODULE,
              "docs/notes.md": (
                  "# notes\n\n```sh\n"
                  "export PKG_EXPERIMENTAL_MODE=1  # turns on the experimental path\n"
                  "```\n")})
    assert item(check(repo, snap), drift.NEW_DARK_SWITCH,
                "dark-switch:PKG_EXPERIMENTAL_MODE").blocking


def test_the_file_this_page_generates_against_cannot_document_a_switch(based):
    """docs/architecture-narrative.md is rendered INTO the artifact this gate
    guards. Counting it would let the page document its own findings away."""
    repo, snap = based
    mk(repo, {"pkg/wired.py": DARK_MODULE,
              "docs/architecture-narrative.md":
                  "## Drift {#drift}\n\nSet `PKG_EXPERIMENTAL_MODE=1` to enable the "
                  "experimental routing path in the planner.\n"})
    assert item(check(repo, snap), drift.NEW_DARK_SWITCH,
                "dark-switch:PKG_EXPERIMENTAL_MODE").blocking


def test_a_generated_document_cannot_document_a_switch(based):
    repo, snap = based
    mk(repo, {"pkg/wired.py": DARK_MODULE,
              "docs/inventory.md": (
                  "GENERATED by the inventory tool -- do not hand-edit.\n\n"
                  "Set `PKG_EXPERIMENTAL_MODE=1` to enable the experimental path.\n")})
    assert item(check(repo, snap), drift.NEW_DARK_SWITCH,
                "dark-switch:PKG_EXPERIMENTAL_MODE").blocking


def test_a_described_operator_form_does_document_a_switch(based):
    """The positive case. A rule nothing can satisfy is a rule that gets
    deleted, so the honest documentation of a switch must actually work."""
    repo, snap = based
    mk(repo, {"pkg/wired.py": DARK_MODULE,
              "docs/flags.md": (
                  "Set `PKG_EXPERIMENTAL_MODE=1` to enable the experimental routing "
                  "path; leave it unset in production.\n")})
    report = check(repo, snap)
    assert drift.NEW_DARK_SWITCH not in kinds(report)


def test_a_longer_documented_name_does_not_document_a_shorter_switch(based):
    repo, snap = based
    mk(repo, {
        "pkg/wired.py": ("import os\nfrom pkg import deep\n"
                         "ON = os.environ.get('PKG_LEVEL', '') == '1'\n"),
        "docs/flags.md": "Set `PKG_LEVEL_MAX` to raise the ceiling on retries.\n",
    })
    report = check(repo, snap)
    item(report, drift.NEW_DARK_SWITCH, "dark-switch:PKG_LEVEL")


# ------------------------------------------------------------- BYPASS: H4

def test_a_module_reached_only_by_a_test_is_its_own_kind(based):
    """H4. A test that merely imports a module used to clear NEW ISLAND
    outright: islands 1 -> 0, FAILED -> OK, nothing printed. Since every module
    here lands with a test, the loudest alarm the gate has could not fire.

    The rule is KEPT -- a test is evidence somebody means to wire the thing, so
    it does not block -- but its consequence is now a named kind, a list in the
    snapshot and a count that moves in the diff."""
    repo, snap = based
    mk(repo, {"pkg/lonely.py": "VALUE = 9\n",
              "tests/test_lonely.py": "from pkg import lonely\n"})

    report = check(repo, snap)
    found = item(report, drift.TEST_ONLY, "test-only:pkg/lonely.py")
    assert found.blocking is False, "the rule is kept: a test is intent"
    assert report.ok is True
    assert drift.NEW_ISLAND not in kinds(report)
    # ... but it is legible, not silent
    assert "TEST ONLY (1)" in report.render()
    assert "pkg/lonely.py" in report.render()
    assert report.state["counts"]["test_only"] == 1
    assert report.state["test_only"] == ["pkg/lonely.py"]


def test_a_test_only_module_is_recorded_in_the_baseline_as_its_own_list(based):
    repo, snap = based
    mk(repo, {"pkg/lonely.py": "VALUE = 9\n",
              "tests/test_lonely.py": "from pkg import lonely\n"})
    drift.refresh(repo, snap)
    doc = read(snap)
    assert doc["islands"] == ["pkg/lonely.py"]
    assert doc["test_only"] == ["pkg/lonely.py"]
    assert doc["counts"]["test_only"] == 1


def test_losing_the_only_test_turns_a_test_only_module_into_an_island(based):
    """The consequence of the rule, made visible in the other direction."""
    repo, snap = based
    mk(repo, {"pkg/lonely.py": "VALUE = 9\n",
              "tests/test_lonely.py": "from pkg import lonely\n"})
    drift.refresh(repo, snap)
    assert check(repo, snap).ok is True

    (repo / "tests" / "test_lonely.py").unlink()
    report = check(repo, snap)
    assert report.ok is False
    found = item(report, drift.NEW_ISLAND, "island:pkg/lonely.py")
    assert "covered by a test in the snapshot" in found.detail


# ------------------------------------------------------------- BYPASS: H6

def test_a_narrowed_ignore_configuration_cannot_pass_as_a_clean_one(based, monkeypatch):
    """H6. ``DAEDALUS_IGNORE=secret.py`` took the gate from FAILED/1/1 to
    OK/0/0 and printed nothing. The snapshot recorded nothing about the
    configuration it was taken under, so a green result was indistinguishable
    from a narrowed one."""
    repo, snap = based
    assert read(snap)["ignore"] == {"env": "", "file": ""}

    monkeypatch.setenv("DAEDALUS_IGNORE", "orphan.py")
    report = check(repo, snap)
    assert report.ok is False
    found = item(report, drift.IGNORE_DRIFT, "ignore:config")
    assert "orphan.py" in found.subject
    assert found.blocking is True


def test_deleting_the_recorded_configuration_is_not_a_quieter_narrowing(based, monkeypatch):
    """An absent field reads as "nothing was excluded", never as "skip this
    check" -- otherwise removing one line is a cheaper bypass than the
    variable it was recording."""
    repo, snap = based
    doc = read(snap)
    doc.pop("ignore")
    doc[drift.DIGEST_KEY] = drift._digest(doc)
    write(snap, doc)
    assert drift.IGNORE_DRIFT not in kinds(check(repo, snap))

    monkeypatch.setenv("DAEDALUS_IGNORE", "orphan.py")
    report = check(repo, snap)
    assert report.ok is False
    item(report, drift.IGNORE_DRIFT, "ignore:config")


def test_an_ignore_file_appearing_is_also_a_configuration_change(based):
    repo, snap = based
    mk(repo, {".daedalusignore": "pkg/orphan.py\n"})
    report = check(repo, snap)
    assert report.ok is False
    item(report, drift.IGNORE_DRIFT, "ignore:config")


def test_a_narrowing_cannot_be_waived_with_an_acceptance(based, monkeypatch):
    repo, snap = based
    monkeypatch.setenv("DAEDALUS_IGNORE", "orphan.py")
    accept(snap, "ignore:config", why="scoped run for the era-4 sweep")
    report = check(repo, snap)
    assert report.ok is False
    assert item(report, drift.IGNORE_DRIFT, "ignore:config").blocking
    item(report, drift.STALE_ACCEPTANCE, "acceptance:ignore:config")


def test_the_gate_does_not_read_the_tree_through_the_ignore_configuration(based, monkeypatch):
    """Belt and braces. The gate reads the tree through reach, which walks the
    filesystem, so a narrowing cannot hide a module from it at all -- the
    recorded configuration above is the second line of defence, not the only
    one."""
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    monkeypatch.setenv("DAEDALUS_IGNORE", "orphan.py")
    state = scan(repo)
    assert "pkg/orphan.py" in state["modules"]
    assert "pkg/orphan.py" in state["islands"]


# ------------------------------------------------------------- BYPASS: M1

def test_an_unparsable_module_is_reported_not_swallowed(based):
    """M1. The env scan caught SyntaxError and ``continue``d, and ScanResult
    had nowhere to say so: an unparsable module with an off-by-default gate in
    it passed clean, mentioned nowhere."""
    repo, snap = based
    # imported from a reached module, so the ONLY finding is the parse failure
    mk(repo, {"pkg/wired.py": "from pkg import deep\nfrom pkg import broken\n",
              "pkg/broken.py": "import os\nif os.environ.get('PKG_X'):\ndef (:\n"})

    report = check(repo, snap)
    assert report.ok is False
    found = item(report, drift.UNPARSABLE, "unparsable:pkg/broken.py")
    assert "could not be parsed" in found.detail
    assert report.state["counts"]["unparsable"] == 1
    assert "UNPARSABLE (1)" in report.render()
    assert drift.NEW_ISLAND not in kinds(report)


def test_an_unparsable_module_is_acceptable_with_a_date(based):
    repo, snap = based
    mk(repo, {"pkg/wired.py": "from pkg import deep\nfrom pkg import broken\n",
              "pkg/broken.py": "def (:\n"})
    accept(snap, "unparsable:pkg/broken.py",
           why="vendored fixture; the parser upgrade lands next week")
    assert check(repo, snap).ok is True


# ------------------------------------------------------------- acceptances

def test_accepted_item_does_not_fail_the_gate(based):
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    accept(snap, "island:pkg/orphan.py", since="2026-07-20", until="2026-08-20")

    report = check(repo, snap)
    assert report.ok is True
    found = item(report, drift.NEW_ISLAND, "island:pkg/orphan.py")
    assert found.accepted is True
    assert found.blocking is False
    assert "accepted until 2026-08-20" in found.note
    assert "follow-up commit" in found.note, "the WHY has to reach the reader"
    assert drift.STALE_ACCEPTANCE not in kinds(report)


def test_acceptance_past_its_horizon_resurfaces(based):
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    accept(snap, "island:pkg/orphan.py", since="2026-05-01", until="2026-07-01")

    report = check(repo, snap, today=date(2026, 7, 28))
    assert report.ok is False
    found = item(report, drift.NEW_ISLAND, "island:pkg/orphan.py")
    assert found.accepted is False
    assert found.blocking is True
    assert "EXPIRED on 2026-07-01" in found.note
    assert "outlived its horizon" in found.note
    assert drift.STALE_ACCEPTANCE not in kinds(report)


def test_acceptance_is_valid_up_to_and_including_its_last_day(based):
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    accept(snap, "island:pkg/orphan.py", since="2026-06-01", until="2026-07-28")

    assert check(repo, snap, today=date(2026, 7, 28)).ok is True
    assert check(repo, snap, today=date(2026, 7, 29)).ok is False


def test_acceptance_beyond_the_horizon_cap_is_invalid(based):
    """``"until": "2099-01-01"`` is the obvious way to defeat an expiring
    acceptance, so it must not work."""
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    accept(snap, "island:pkg/orphan.py", since="2026-07-20", until="2099-01-01")

    report = check(repo, snap)
    assert report.ok is False
    bad = item(report, drift.INVALID_ACCEPTANCE, "acceptance:island:pkg/orphan.py")
    assert str(drift.MAX_HORIZON_DAYS) in bad.detail
    still = item(report, drift.NEW_ISLAND, "island:pkg/orphan.py")
    assert still.blocking is True
    assert "invalid" in still.note


@pytest.mark.parametrize("bad, expect", [
    ({"why": "wip"}, "at least"),
    ({"why": ""}, "at least"),
    ({"since": "soon"}, "'since' must be an ISO date"),
    ({"until": "later"}, "'until' must be an ISO date"),
    ({"since": "2026-08-20", "until": "2026-07-20"}, "before 'since'"),
    ({"since": "2999-01-01", "until": "2999-03-01"}, "future"),
])
def test_malformed_acceptances_suppress_nothing(based, bad, expect):
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    kwargs = {"since": "2026-07-20", "until": "2026-08-20",
              "why": "the CLI wiring lands in the follow-up commit"}
    kwargs.update(bad)
    accept(snap, "island:pkg/orphan.py", **kwargs)

    report = check(repo, snap)
    assert report.ok is False
    assert expect in item(report, drift.INVALID_ACCEPTANCE).detail
    assert item(report, drift.NEW_ISLAND, "island:pkg/orphan.py").blocking


def test_acceptance_matching_nothing_is_stale_and_blocks(based):
    """An acceptance list that can accumulate dead prose becomes a graveyard
    nobody dares delete."""
    repo, snap = based
    accept(snap, "island:pkg/never_existed.py")

    report = check(repo, snap)
    assert report.ok is False
    stale = item(report, drift.STALE_ACCEPTANCE, "acceptance:island:pkg/never_existed.py")
    assert "delete this acceptance" in stale.remedy


def test_a_wildcard_acceptance_matches_nothing_and_still_blocks(based):
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    accept(snap, "island:*")
    report = check(repo, snap)
    assert report.ok is False
    item(report, drift.STALE_ACCEPTANCE, "acceptance:island:*")
    assert item(report, drift.NEW_ISLAND, "island:pkg/orphan.py").blocking


def test_acceptance_goes_stale_once_the_island_is_wired(based):
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    accept(snap, "island:pkg/orphan.py")
    assert check(repo, snap).ok is True

    mk(repo, {"pkg/__init__.py": "from pkg import wired\nfrom pkg import orphan\n"})
    report = check(repo, snap)
    item(report, drift.STALE_ACCEPTANCE, "acceptance:island:pkg/orphan.py")
    assert report.ok is False


def test_acceptance_does_not_ride_along_on_the_good_news(based):
    """An acceptance sitting on an island that has since been wired matches a
    NOW REACHED item. It must still go stale, or acceptances survive by
    attaching themselves to the very outcome that made them pointless."""
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    drift.refresh(repo, snap)                            # baseline WITH the island
    assert read(snap)["islands"] == ["pkg/orphan.py"]
    accept(snap, "island:pkg/orphan.py")
    mk(repo, {"pkg/__init__.py": "from pkg import wired\nfrom pkg import orphan\n"})

    report = check(repo, snap)
    good = item(report, drift.NOW_REACHED, "island:pkg/orphan.py")
    assert good.accepted is False
    item(report, drift.STALE_ACCEPTANCE, "acceptance:island:pkg/orphan.py")
    assert report.ok is False


def test_the_how_to_accept_hint_never_suggests_accepting_an_acceptance(based):
    repo, snap = based
    accept(snap, "island:pkg/never_existed.py")

    text = check(repo, snap).render()
    assert "STALE ACCEPTANCE" in text
    assert '"item": "acceptance:' not in text, (
        "an acceptance is not an acceptable item -- suggesting one teaches the "
        "reader to paper over the hygiene failure")
    assert "To accept temporarily" not in text


def test_dark_switch_and_doc_drift_are_acceptable_too(based):
    repo, snap = based
    mk(repo, {"pkg/wired.py": ("import os\nfrom pkg import deep\n"
                               "ON = os.environ.get('PKG_TURBO', '') == '1'\n")})
    accept(snap, "dark-switch:PKG_TURBO",
           why="documented in the flags ADR now in review")
    accept(snap, "doc-drift:code-only:PKG_TURBO",
           why="documented in the flags ADR now in review")

    report = check(repo, snap)
    assert item(report, drift.NEW_DARK_SWITCH, "dark-switch:PKG_TURBO").accepted
    assert report.ok is True


def test_a_test_only_finding_is_not_something_to_accept(based):
    """It never blocks, so an acceptance for it can only be dead prose."""
    repo, snap = based
    mk(repo, {"pkg/lonely.py": "VALUE = 9\n",
              "tests/test_lonely.py": "from pkg import lonely\n"})
    accept(snap, "test-only:pkg/lonely.py", why="wiring lands with the CLI work")
    report = check(repo, snap)
    item(report, drift.STALE_ACCEPTANCE, "acceptance:test-only:pkg/lonely.py")
    assert report.ok is False


# --------------------------------------------------------------- refreshing

def test_refresh_never_bakes_an_accepted_item_into_the_baseline(based):
    """The load-bearing rule. If ``--refresh`` could absorb an accepted island,
    it would be a third, undated way to accept -- and the easiest one."""
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    accept(snap, "island:pkg/orphan.py", since="2026-07-20", until="2026-08-20")

    drift.refresh(repo, snap)
    doc = read(snap)

    assert "pkg/orphan.py" not in doc["islands"]
    assert doc["counts"]["islands"] == 0
    assert [a["item"] for a in doc["acceptances"]] == ["island:pkg/orphan.py"]

    after = check(repo, snap)
    assert after.ok is True
    assert item(after, drift.NEW_ISLAND, "island:pkg/orphan.py").accepted
    assert check(repo, snap, today=date(2027, 1, 1)).ok is False


def test_refresh_after_deleting_the_acceptance_is_the_permanent_escape(based):
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    before = read(snap)["counts"]["islands"]

    drift.refresh(repo, snap)
    doc = read(snap)

    assert doc["islands"] == ["pkg/orphan.py"]
    assert doc["counts"]["islands"] == before + 1, (
        "the count has to move, because the reviewed diff is the whole control")
    assert check(repo, snap).ok is True


def test_refresh_carries_acceptances_forward_verbatim(based):
    repo, snap = based
    accept(snap, "island:pkg/orphan.py", who="kaya")
    original = read(snap)["acceptances"]

    drift.refresh(repo, snap)
    assert read(snap)["acceptances"] == original


def test_refresh_re_signs_the_digest(based):
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    drift.refresh(repo, snap)
    doc = read(snap)
    assert doc[drift.DIGEST_KEY] == drift._digest(doc)
    assert drift.INVALID_SNAPSHOT not in kinds(check(repo, snap))


# ---------------------------------------------------- snapshot integrity

def test_hand_edited_counts_are_caught(based):
    """The exact failure this module exists to prevent: a number in an artifact
    that no longer matches the list printed beside it."""
    repo, snap = based
    edit_signed(snap, counts={"modules": 136, "islands": 8, "test_only": 0,
                              "dark_switches": 2, "doc_drift": 0,
                              "unparsable": 0})

    report = check(repo, snap)
    assert report.ok is False
    bad = item(report, drift.INVALID_SNAPSHOT, "snapshot:counts.modules")
    assert "snapshot says 136" in bad.detail


def test_unreadable_snapshot_reports_instead_of_crashing(based):
    repo, snap = based
    snap.write_text("{ this is not json", encoding="utf-8")

    report = check(repo, snap)
    assert report.ok is False
    item(report, drift.INVALID_SNAPSHOT, "snapshot:unreadable")
    assert "re-baseline" in report.render()


def test_snapshot_missing_lists_degrade_to_first_principles(based):
    """A snapshot stripped down to the schema and a digest must not raise;
    every absent list simply reads as empty."""
    repo, snap = based
    doc = {"schema": drift.SCHEMA_VERSION}
    doc[drift.DIGEST_KEY] = drift._digest(doc)
    write(snap, doc)
    report = check(repo, snap)
    assert isinstance(report.ok, bool)
    assert drift.INVALID_SNAPSHOT not in kinds(report)


# ------------------------------------------------------------- determinism

def test_scan_is_deterministic(repo):
    assert scan(repo) == scan(repo)


def test_snapshot_bytes_are_stable_and_sorted(repo, snap, tmp_path):
    state = scan(repo)
    first = drift.write_snapshot(snap, state, ())
    second = drift.write_snapshot(tmp_path / "other.json", state, ())

    assert first == second
    assert first.endswith("\n")
    assert "\r" not in first, "a CR would make the git diff unreadable on the other OS"

    doc = json.loads(first)
    for key in ("modules", "islands", "test_only", "dark_switches",
                "doc_drift", "unparsable"):
        assert doc[key] == sorted(doc[key])
    assert "generated_at" not in first, (
        "a timestamp would put a diff in every run and train reviewers to skip it")
    assert doc[drift.DIGEST_KEY] == drift._digest(doc)


def test_report_ordering_is_stable(based):
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n", "pkg/other.py": "VALUE = 8\n"})
    first = check(repo, snap).render()
    second = check(repo, snap).render()
    assert first == second
    assert first.index("pkg/orphan.py") < first.index("pkg/other.py")


# ------------------------------------------------------------------ render

def test_render_names_the_item_and_what_to_do_about_it(based):
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    text = check(repo, snap).render()

    assert "FAILED" in text
    assert "NEW ISLAND (1)" in text
    assert "pkg/orphan.py" in text
    assert "wire it, document it, delete it, or accept it explicitly" in text
    # the report must show HOW to accept, or the gate gets bypassed instead
    assert '"item": "island:pkg/orphan.py"' in text


def test_report_is_serialisable_for_a_non_terminal_caller(based):
    repo, snap = based
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n"})
    report = check(repo, snap)

    assert report.counts == {drift.NEW_ISLAND: 1}
    payload = [i.as_dict() for i in report.items]
    assert json.loads(json.dumps(payload)) == payload
    assert payload[0]["key"] == "island:pkg/orphan.py"


def test_default_snapshot_path_is_the_committed_one(repo):
    report = drift.check(repo, write_missing=True)
    assert report.first_run
    assert Path(report.snapshot_path) == (repo / drift.SNAPSHOT_REL).resolve()
    assert (repo / drift.SNAPSHOT_REL).is_file()
