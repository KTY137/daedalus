"""The engine reads the two idioms it used to be blind to.

WHY A SECOND FILE. tests/test_mapping_reach.py drives one hostile mini-repo
whose shape is a fixed contract; adding a package facade to it would change
every count that file pins. These cases need their own repo, so they get their
own file.

WHAT WENT WRONG, MEASURED ON 2026-09-03 by an independent survey
(docs/G1_LOOSE_PARTS_SURVEY_20260903.md) and reproduced here:

  * a package ``__init__.py`` was registered under ``pkg.__init__``, a name no
    import statement ever writes, so ``daedalus/resources/__init__.py`` -- a
    138-line module with five production callers -- was reported ``orphan``
    with the reason "imports nothing and nothing imports it";
  * ``import_module(f"{__name__}.missions")`` was unreadable, so the flagship
    mission subsystem below ``daedalus/orchestration/__init__.py`` was reported
    as islands;
  * and the detector matched the bare name ``import_module`` only, so
    ``from importlib import import_module as _import_module`` -- the spelling
    BOTH lazy facades in this repository use -- made their dynamic calls
    invisible, taking their literal tables with them.

The third was not in the survey. It was found by fixing the first two and
measuring no change.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from daedalus.mapping import analyse
from daedalus.mapping.reach import (
    _dynamic_aliases,
    _py_dotted,
    _scan,
    _static_join,
    _table_strings,
)


PYPROJECT = """\
[build-system]
requires = ["setuptools>=61"]

[project]
name = "mini"
version = "0.0.1"
dependencies = []

[project.scripts]
mini = "mini.cli:main"

[tool.setuptools]
packages = ["mini"]
"""

FILES = {
    "pyproject.toml": PYPROJECT,
    # the entry: reaches the package root by name, and the package by directory
    "mini/cli.py": (
        "from mini.resources import banner\n"
        "from mini.lazy import PUBLIC\n"
        "\n"
        "def main():\n"
        "    print(banner(), PUBLIC)\n"
        "    return 0\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n"
    ),
    "mini/__init__.py": "",
    # a PACKAGE whose __init__ carries the body and is imported by directory name
    "mini/resources/__init__.py": (
        "from .helper import shout\n"
        "\n"
        "def banner():\n"
        "    return shout('mini')\n"
    ),
    "mini/resources/helper.py": "def shout(x):\n    return x.upper()\n",
    # a facade with an f-string self-reference AND an aliased import_module
    "mini/lazy/__init__.py": (
        "from importlib import import_module as _import_module\n"
        "\n"
        "_TABLE = frozenset({'tabled'})\n"
        "_NOT_A_TABLE = 'prose mentioning tabled and unreferenced'\n"
        "PUBLIC = 'public'\n"
        "\n"
        "def load_missions():\n"
        "    return _import_module(f'{__name__}.missions')\n"
        "\n"
        "def __getattr__(name):\n"
        "    if name in _TABLE:\n"
        "        return _import_module(f'{__name__}.{name}')\n"
        "    raise AttributeError(name)\n"
    ),
    "mini/lazy/missions.py": "VALUE = 1\n",
    "mini/lazy/tabled.py": "VALUE = 2\n",
    "mini/lazy/unreferenced.py": "VALUE = 3\n",
}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def _facts(report, module):
    got = report.get(module)
    assert got is not None, f"{module} missing from the report"
    return got


# ------------------------------------------------- a package is not pkg.__init__

def test_a_package_binds_to_the_name_an_import_actually_writes() -> None:
    assert _py_dotted("daedalus/resources/__init__.py") == "daedalus.resources"
    assert _py_dotted("daedalus/router.py") == "daedalus.router"
    # not a package init: the suffix must survive where it is a real module name
    assert _py_dotted("pkg/__init__helper.py") == "pkg.__init__helper"


def test_a_package_init_with_importers_is_not_an_orphan(repo: Path) -> None:
    report = analyse(repo)
    facts = _facts(report, "mini/resources/__init__.py")
    assert facts.classification == "reachable", facts.reason
    assert "mini/cli.py" in facts.imported_by


def test_relative_imports_inside_a_package_init_still_anchor_at_the_package(
    repo: Path,
) -> None:
    """The regression that stripping ``__init__`` introduced, pinned.

    ``from .helper import shout`` inside ``mini/resources/__init__.py`` means
    ``mini.resources.helper``. Anchoring it at the STRIPPED name resolves it to
    ``mini.helper``, which does not exist, and the real edge is lost -- 23
    modules changed class the first time this was measured.
    """
    report = analyse(repo)
    facts = _facts(report, "mini/resources/__init__.py")
    assert "mini/resources/helper.py" in facts.imports
    assert _facts(report, "mini/resources/helper.py").classification == "reachable"


# --------------------------------------------------------- computable f-strings

def test_an_f_string_over_dunder_name_is_a_literal_target() -> None:
    tree = ast.parse("import_module(f'{__name__}.missions')")
    call = tree.body[0].value
    assert _static_join(call.args[0], "pkg.sub") == "pkg.sub.missions"


def test_an_f_string_with_a_variable_part_stays_unreadable() -> None:
    tree = ast.parse("import_module(f'{__name__}.{name}')")
    call = tree.body[0].value
    assert _static_join(call.args[0], "pkg.sub") is None


def test_the_self_referencing_facade_reaches_its_submodule(repo: Path) -> None:
    report = analyse(repo)
    facts = _facts(report, "mini/lazy/missions.py")
    assert facts.classification == "reachable", facts.reason


# ------------------------------------------------------------- aliased importlib

def test_the_detector_reads_the_alias_rather_than_the_bare_name() -> None:
    aliased = ast.parse("from importlib import import_module as _import_module\n")
    assert "_import_module" in _dynamic_aliases(aliased)
    plain = ast.parse("import json\n")
    assert _dynamic_aliases(plain) == {"__import__", "import_module"}


def test_an_aliased_dynamic_call_is_seen_at_all(repo: Path) -> None:
    src = _scan("mini/lazy/__init__.py", FILES["mini/lazy/__init__.py"])
    assert src.dynamic, "the unreadable call must be recorded as a hole"
    assert src.dyn_targets == {"mini.lazy.missions"}


# ------------------------------------------------------------- literal tables

def test_a_table_is_read_and_prose_is_not() -> None:
    tree = ast.parse(FILES["mini/lazy/__init__.py"])
    strings = _table_strings(tree)
    assert "tabled" in strings
    assert "prose mentioning tabled and unreferenced" not in strings


def test_a_tabled_module_is_unknown_not_island_and_not_reachable(
    repo: Path,
) -> None:
    """The load-bearing judgement of this packet.

    A name in a dispatch table proves the module CAN be loaded through the
    facade, not that anything asks for it. Calling it ``reachable`` is the
    silent error the engine's own docstring says is worse than a false island;
    calling it ``island`` is the false accusation. ``unknown`` is the honest
    class, and it carries the reason.
    """
    report = analyse(repo)
    facts = _facts(report, "mini/lazy/tabled.py")
    assert facts.classification == "unknown", facts.reason
    assert "mini/lazy/tabled.py" not in _facts(report, "mini/lazy/__init__.py").imports


def test_a_module_the_table_does_not_name_is_not_laundered(repo: Path) -> None:
    """The guard against a table laundering the whole package.

    ``unreferenced.py`` sits beside ``tabled.py`` and is named only in prose.
    It comes back ``orphan`` rather than ``island`` because it imports nothing
    either, which is the stricter of the two unreached classes; what matters is
    that it is NOT ``unknown``. If it were, the harvester would be reading
    something other than container literals.
    """
    report = analyse(repo)
    assert _facts(report, "mini/lazy/unreferenced.py").classification == "orphan"


def test_candidates_are_offered_only_where_an_unreadable_call_exists() -> None:
    """No hole, no candidates.

    A module holding a dotted string in a list must not gain edges it never
    traverses, so the table is consulted only when the walk has already failed
    to read a dynamic call in that same module.
    """
    without = _scan("m.py", "TABLE = ['pkg.thing']\n")
    assert without.dyn_candidates == set()
    with_hole = _scan(
        "m.py",
        "from importlib import import_module\n"
        "TABLE = ['pkg.thing']\n"
        "def f(name):\n    return import_module(name)\n",
    )
    assert with_hole.dyn_candidates == {"pkg.thing"}
