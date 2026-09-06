"""The ``center:`` directive in ``.daedalusignore`` is read.

WHY THIS PACKET EXISTS (G1-MAP-03). This repository's ``.daedalusignore``
opens with

    # Project scope declaration (G-02). Weakest tier: an explicit --center or
    # DAEDALUS_CENTER still overrides.
    center: daedalus, tools, apps/web/src

and nothing has ever read it `[MEASURED 2026-09-03]`. ``project_scope`` took
its center from an explicit argument or ``DAEDALUS_CENTER`` only, and
``_parse_line`` turned the line into an ignore *pattern* -- an anchored pattern
containing a slash, matching no path in the tree. The comment describes a
precedence that was never implemented, so the declaration was inert.

WHAT IT COSTS. ``daedalus/structcore/index.py`` builds its scope with
``center=None`` from every ordinary caller, so the whole repository was treated
as core. That module's own comment states the stake: shell files are withheld
from every metric, and doing so "costs ~2% (the per-file parse) and saves ~96%
(clone passes)". A declared boundary nothing reads is a hotspot ranking, a clone
pass and a slice expansion that all range over vendored trees and generated
skeletons.

PRECEDENCE, exactly as the file's own comment states it, weakest last:

    explicit argument  >  DAEDALUS_CENTER  >  center: in .daedalusignore

DELIBERATELY OUT OF SCOPE: the reachability engine. ``daedalus/mapping/reach.py``
builds its scope with an explicit empty center and the committed ignore rules
only, and G1-MAP-02 pinned why -- the drift gate must not be narrowable by an
environment variable, and the island census should not silently stop covering
``scripts/`` and ``experiments/`` because a center line moved. Reach's choice is
an explicit argument, which is the strongest tier, so it is unaffected by this
change. ``tests/test_mapping_scope.py`` pins that it stays unaffected.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.structcore.ignore import (
    _parse_line,
    load_declared_center,
    project_scope,
)


IGNORE_FILE = """\
# Project scope declaration
center: mini, tools

runs/
"""


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".daedalusignore").write_text(IGNORE_FILE, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------ the directive

def test_the_directive_is_parsed_into_center_roots(repo: Path) -> None:
    assert load_declared_center(repo) == ("mini", "tools")


def test_a_missing_file_declares_no_center(tmp_path: Path) -> None:
    assert load_declared_center(tmp_path) == ()


def test_the_directive_is_not_also_an_ignore_pattern() -> None:
    """It used to become an anchored pattern that matched nothing.

    Leaving it in the rule list is not harmless: ``matches()`` is last-match
    wins, so a stray rule is a latent behaviour change waiting for a path that
    happens to look like it.
    """
    assert _parse_line("center: mini, tools") is None
    # a real pattern that merely starts with the word is still a pattern
    assert _parse_line("centered/") is not None


def test_the_declared_center_reaches_the_scope(repo: Path) -> None:
    scope = project_scope(repo)
    assert scope.center == ("mini", "tools")
    assert scope.in_center("mini/app.py") is True
    assert scope.is_shell("thirdparty/lib.py") is True


def test_ignore_rules_still_load_alongside_the_directive(repo: Path) -> None:
    scope = project_scope(repo)
    assert scope.is_shell("runs/artifact.py") is True


# ------------------------------------------------------------- precedence

def test_an_explicit_argument_beats_the_file(repo: Path) -> None:
    assert project_scope(repo, center=["other"]).center == ("other",)


def test_the_environment_beats_the_file(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("DAEDALUS_CENTER", "fromenv")
    assert project_scope(repo).center == ("fromenv",)


def test_an_explicit_argument_beats_the_environment(
    repo: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("DAEDALUS_CENTER", "fromenv")
    assert project_scope(repo, center=["explicit"]).center == ("explicit",)


def test_the_center_is_part_of_the_scope_fingerprint(repo: Path) -> None:
    """Two scopes that see different trees must not share a cache key."""
    declared = project_scope(repo)
    overridden = project_scope(repo, center=["other"])
    assert declared.fingerprint != overridden.fingerprint


# --------------------------------------------------- the tree this was found in

def test_this_repository_declares_its_own_center() -> None:
    root = Path(__file__).resolve().parents[1]
    assert load_declared_center(root) == ("apps/web/src", "daedalus", "tools")
