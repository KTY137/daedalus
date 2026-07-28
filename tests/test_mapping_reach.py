"""Reachability engine tests, driven by a synthetic mini-repo of known shape.

The fixture is deliberately small and deliberately hostile: it contains one
console-script entry point, a three-deep import chain behind it, a subcommand
whose target is imported LAZILY inside a module-local helper, a genuine island
(plus the island's own private helper), a re-export shim, an orphan, and a
module nameable only through a registry string. Each of those is a distinct
classification, so a regression that collapses two of them together fails here
rather than in a report nobody re-reads.

Nothing here touches the network, a model, or a vendor CLI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.mapping import analyse
from daedalus.mapping.reach import ReachReport


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

# The shape under test. ``beta`` is the load-bearing case: its module is
# imported nowhere at module level -- only inside ``_run_beta``, which is only
# called from inside an elif branch. A module-level import scan reports it as an
# island, which is the exact false accusation this engine exists to avoid.
CLI = '''\
"""mini command line."""
import sys

# A registry naming a module as a STRING. Static walking cannot follow this.
_PLUGINS = ("mini.ghost",)


def _load(name):
    """Dynamic dispatch with a non-literal argument -- deliberately opaque."""
    import importlib
    return importlib.import_module(name)


def _run_beta(argv):
    from .beta import run
    return run(argv)


def main():
    argv = sys.argv[1:]
    cmd = argv[0] if argv else ""
    if cmd == "alpha":
        from .alpha import go
        go()
    elif cmd == "beta":
        _run_beta(argv[1:])
    elif cmd == "gamma":
        from .gamma import go as g
        g()
    else:
        print("unknown")


if __name__ == "__main__":
    main()
'''

FILES = {
    "pyproject.toml": PYPROJECT,
    "mini/__init__.py": '"""mini package."""\n',
    "mini/cli.py": CLI,
    "mini/alpha.py": '"""alpha."""\nfrom .chain import step\n\n\ndef go():\n    return step()\n',
    "mini/chain.py": '"""chain."""\nfrom .leaf import LEAF\n\n\ndef step():\n    return LEAF\n',
    "mini/leaf.py": '"""leaf."""\n\nLEAF = 1\n',
    "mini/beta.py": '"""beta -- imported only inside a CLI branch helper."""\n\n\ndef run(argv):\n    return len(argv)\n',
    "mini/gamma.py": '"""gamma."""\n\n\ndef go():\n    return "g"\n',
    "mini/lonely.py": '"""A genuine island."""\nfrom .lonely_helper import helper\n\n\ndef unused():\n    return helper()\n',
    "mini/lonely_helper.py": '"""Private to the island."""\n\n\ndef helper():\n    return 1\n',
    "mini/shim.py": '"""Re-export surface."""\nfrom .leaf import LEAF\n\n__all__ = ["LEAF"]\n',
    "mini/orphan.py": '"""Imports nothing, imported by nothing."""\n\nVALUE = 1\n',
    "mini/ghost.py": '"""Reachable only through the _PLUGINS registry string."""\n\n\ndef go():\n    return "ghost"\n',
    "tests/test_lonely.py": "from mini.lonely import unused\n\n\ndef test_unused():\n    assert unused() == 1\n",
}


@pytest.fixture()
def mini_repo(tmp_path: Path) -> Path:
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def report(mini_repo: Path) -> ReachReport:
    return analyse(mini_repo)


def _cls(report: ReachReport, module: str) -> str:
    facts = report.get(module)
    assert facts is not None, f"{module} missing from the report"
    return facts.classification


# ---------------------------------------------------------------- entries

def test_console_script_is_discovered_not_hardcoded(report: ReachReport):
    scripts = [e for e in report.entry_points if e.kind == "script"]
    assert [e.name for e in scripts] == ["mini"]
    assert scripts[0].module == "mini/cli.py"
    assert scripts[0].function == "main"


def test_cli_subcommands_come_from_the_dispatch_chain(report: ReachReport):
    names = sorted(e.name for e in report.entry_points if e.kind == "cli")
    assert names == ["alpha", "beta", "gamma"]


def test_main_guard_is_an_entry_point(report: ReachReport):
    guards = [e.name for e in report.entry_points if e.kind == "main_guard"]
    assert guards == ["mini.cli"]


# ---------------------------------------------------------- classification

def test_entry_module_classified_as_entry(report: ReachReport):
    assert _cls(report, "mini/cli.py") == "entry"


def test_chain_behind_an_entry_is_reachable_with_shortest_path(report: ReachReport):
    leaf = report.get("mini/leaf.py")
    assert leaf.classification == "reachable"
    assert leaf.path == ("mini/cli.py", "mini/alpha.py", "mini/chain.py",
                         "mini/leaf.py")
    assert leaf.depth == 3
    assert leaf.entry == "cli:alpha"


def test_lazy_import_inside_a_cli_branch_is_reachable_not_island(report: ReachReport):
    """The regression this engine exists for.

    ``mini/beta.py`` has zero module-level importers. It is imported inside
    ``_run_beta``, which is called only from an elif branch. Anything that
    scans module-level imports calls it an island."""
    beta = report.get("mini/beta.py")
    assert beta.classification == "reachable", beta.reason
    assert beta.entry == "cli:beta"
    assert beta.path == ("mini/cli.py", "mini/beta.py")


def test_lazy_import_directly_in_a_branch_is_reachable(report: ReachReport):
    gamma = report.get("mini/gamma.py")
    assert gamma.classification == "reachable"
    assert gamma.entry == "cli:gamma"


def test_genuine_island_is_reported_as_island(report: ReachReport):
    assert _cls(report, "mini/lonely.py") == "island"
    assert _cls(report, "mini/lonely_helper.py") == "island"


def test_shim_is_detected_structurally(report: ReachReport):
    shim = report.get("mini/shim.py")
    assert shim.is_shim is True
    assert shim.classification == "shim"
    assert report.get("mini/cli.py").is_shim is False


def test_orphan_imports_nothing_and_is_imported_by_nothing(report: ReachReport):
    orphan = report.get("mini/orphan.py")
    assert orphan.classification == "orphan"
    assert orphan.imports == ()
    assert orphan.imported_by == ()


def test_string_named_module_is_unknown_not_island(report: ReachReport):
    """A false island is the failure mode that makes this tool distrusted."""
    ghost = report.get("mini/ghost.py")
    assert ghost.classification == "unknown"
    assert any("mini.ghost" in e for e in ghost.evidence)
    assert "mini/cli.py" in " ".join(ghost.evidence)


def test_non_literal_dynamic_import_is_recorded_as_a_surface(report: ReachReport):
    assert any(s.startswith("mini/cli.py:") for s in report.dynamic_surfaces)


# ------------------------------------------------------------------ tests

def test_test_files_are_not_entry_points(report: ReachReport):
    assert all(not e.module.startswith("tests/") for e in report.entry_points)
    assert _cls(report, "tests/test_lonely.py") == "test"


def test_test_coverage_is_recorded_separately(report: ReachReport):
    lonely = report.get("mini/lonely.py")
    assert lonely.tested_by == ("tests/test_lonely.py",)
    assert lonely.classification == "island", (
        "a module reached only by its own test is the definition of an island")


def test_test_string_literals_do_not_launder_an_island(tmp_path: Path):
    """A test naming a module proves the test imports it, nothing more."""
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (tmp_path / "tests" / "test_names.py").write_text(
        'MODULES = ("mini.lonely", "mini/lonely_helper.py")\n', encoding="utf-8")
    rep = analyse(tmp_path)
    assert rep.get("mini/lonely.py").classification == "island"


# ------------------------------------------------------------------ counts

def test_counts_match_the_classified_modules(report: ReachReport):
    assert sum(report.counts.values()) == len(report.modules)
    for name, n in report.counts.items():
        assert n == len(report.by_class(name))
    assert report.counts["island"] == 2
    assert report.counts["orphan"] == 1
    assert report.counts["shim"] == 1
    assert report.counts["unknown"] == 1


def test_unparsable_files_are_named_never_dropped_silently(mini_repo: Path):
    (mini_repo / "mini" / "broken.py").write_text("def (:\n", encoding="utf-8")
    rep = analyse(mini_repo)
    assert "mini/broken.py" in rep.unparsable
    assert rep.get("mini/broken.py") is not None


# ----------------------------------------------------------- determinism

def test_two_runs_produce_identical_output(mini_repo: Path):
    first = analyse(mini_repo).to_json()
    second = analyse(mini_repo).to_json()
    assert first == second
    assert json.loads(first)["schema"].startswith("daedalus.mapping.reach/")


def test_output_carries_no_clock_or_environment_reading(report: ReachReport):
    blob = report.to_json()
    assert "timestamp" not in blob and "generated_at" not in blob


def test_module_ordering_is_lexicographic(report: ReachReport):
    names = [m.module for m in report.modules]
    assert names == sorted(names)


# ------------------------------------------------- structcore cross-check

def test_supplied_index_edges_are_reported_and_never_unioned(mini_repo: Path):
    """A disagreement with the structural index is a FINDING, not a discovery.

    CONFIGURATION: ``analyse(root, index=...)`` -- an index IS supplied, which
    is the only configuration ``daedalus map`` ever runs in (render.analyse_once
    builds one whenever the caller passes ``index=None``).

    This test asserted the OPPOSITE until today: that the extra edge
    re-classified the module. That is what made the union look intentional, and
    the union is what re-admitted every dead-branch import the walk had
    deliberately withheld. The report records the edge; the graph does not move.
    """
    fake_index = {"import_edges": {"mini/orphan.py": ["mini/leaf.py"]}}
    rep = analyse(mini_repo, index=fake_index)
    assert "mini/orphan.py -> mini/leaf.py" in rep.index_extra_edges
    assert rep.get("mini/orphan.py").classification == "orphan"
    assert rep.get("mini/orphan.py").imports == ()
    assert "mini/orphan.py" not in rep.get("mini/leaf.py").imported_by


def test_index_edges_to_unknown_files_are_ignored(mini_repo: Path):
    rep = analyse(mini_repo, index={"import_edges": {"mini/orphan.py": ["nope/x.py"]}})
    assert rep.index_extra_edges == ()
    assert rep.get("mini/orphan.py").classification == "orphan"


def test_an_index_edge_cannot_carry_a_module_to_an_entry_point(mini_repo: Path):
    """The reachability consequence, stated as reachability rather than as a
    class name: if the ONLY route from an entry point to a module runs through
    an edge this walk refused, the module is not reached.

    CONFIGURATION: an index is supplied. ``mini/cli.py`` is the console-script
    entry module, so unioning one edge out of it is enough to paint anything
    green -- which is exactly the shape the adversary measured.
    """
    (mini_repo / "mini" / "secret.py").write_text(SECRET, encoding="utf-8")
    rep = analyse(mini_repo, index={
        "import_edges": {"mini/cli.py": ["mini/secret.py"]}})
    facts = rep.get("mini/secret.py")
    assert facts.classification != "reachable", facts.reason
    assert facts.entry == ""
    assert facts.path == ()
    assert facts.depth is None
    assert "mini/cli.py -> mini/secret.py" in rep.index_extra_edges


# ------------------------------------------- FALSE REACHABLE (three vectors)
#
# A false island is the failure that makes this tool distrusted. A false
# REACHABLE is worse, because it is silent: the module is painted green and
# nobody looks again. Each of these three costs two lines to write and used to
# work permanently.

def _mini(tmp_path: Path, extra: dict | None = None,
          patch: dict | None = None) -> Path:
    files = dict(FILES)
    files.update(patch or {})
    files.update(extra or {})
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


SECRET = '"""A module nothing runs."""\n\n\ndef go():\n    return "secret"\n'


def test_a_console_script_naming_a_missing_function_is_not_an_entry_point(tmp_path: Path):
    """``ghost = "mini.secret:nosuchfunc"`` in [project.scripts] was classified
    ``entry``, kind ``script:ghost`` -- the strongest claim this report makes --
    for a script that raises the moment anyone invokes it. The target half was
    split off and thrown away without ever being checked."""
    root = _mini(tmp_path, extra={"mini/secret.py": SECRET},
                 patch={"pyproject.toml": PYPROJECT.replace(
                     'mini = "mini.cli:main"',
                     'mini = "mini.cli:main"\nghost = "mini.secret:nosuchfunc"')})
    rep = analyse(root)

    assert "ghost" not in [e.name for e in rep.entry_points]
    assert any("nosuchfunc" in b for b in rep.broken_entries), rep.broken_entries
    assert _cls(rep, "mini/secret.py") != "entry"
    assert _cls(rep, "mini/secret.py") in ("island", "orphan")


def test_a_console_script_naming_a_real_function_still_is_one(tmp_path: Path):
    """The rule has to admit the honest case, or it is just a refusal."""
    root = _mini(tmp_path, extra={"mini/secret.py": SECRET},
                 patch={"pyproject.toml": PYPROJECT.replace(
                     'mini = "mini.cli:main"',
                     'mini = "mini.cli:main"\nreal = "mini.secret:go"')})
    rep = analyse(root)
    assert "real" in [e.name for e in rep.entry_points]
    assert rep.broken_entries == ()
    assert _cls(rep, "mini/secret.py") == "entry"


def test_a_console_script_naming_a_missing_module_is_recorded(tmp_path: Path):
    root = _mini(tmp_path, patch={"pyproject.toml": PYPROJECT.replace(
        'mini = "mini.cli:main"',
        'mini = "mini.cli:main"\nvapour = "mini.nowhere:main"')})
    rep = analyse(root)
    assert "vapour" not in [e.name for e in rep.entry_points]
    assert any("no such module" in b for b in rep.broken_entries)


def test_an_import_under_if_false_is_not_reachability_evidence(tmp_path: Path):
    """A branch the interpreter deletes is not a caller."""
    root = _mini(tmp_path, extra={"mini/secret.py": SECRET},
                 patch={"mini/leaf.py": '"""leaf."""\n\nif False:\n'
                                        "    from . import secret\n\nLEAF = 1\n"})
    rep = analyse(root)
    facts = rep.get("mini/secret.py")
    assert facts.classification == "unknown", facts.reason
    assert "not evidence" in facts.reason
    assert any("mini/leaf.py" in e for e in facts.evidence)
    assert any("if False" in e for e in facts.evidence)
    assert "mini/leaf.py" not in facts.imported_by
    assert any("mini/leaf.py -> mini/secret.py" in w for w in rep.weak_edges)


def test_an_import_under_if_false_is_not_evidence_WITH_AN_INDEX(tmp_path: Path):
    """The same property, in the configuration the product actually ships.

    CONFIGURATION: ``analyse(root, index=...)``. The test above it runs with NO
    index, and that is the one arrangement ``daedalus map`` never uses --
    ``render.analyse_once`` treats ``index=None`` as "build one yourself", so
    every real run supplies one. The property was therefore pinned only where
    it could not fail, and it failed everywhere else: the index's edge set has
    no branch context, so the union put ``mini/leaf.py -> mini/secret.py``
    straight back and the module printed ``reachable``.

    The index dict here is the real structcore shape ({"import_edges": {src:
    [tgt]}}) carrying exactly the edge structcore does in fact derive for this
    source; the end-to-end version, through a genuine structcore index and
    ``daedalus map`` itself, is in tests/test_mapping_cli.py.
    """
    root = _mini(tmp_path, extra={"mini/secret.py": SECRET},
                 patch={"mini/leaf.py": '"""leaf."""\n\nif False:\n'
                                        "    from . import secret\n\nLEAF = 1\n"})
    rep = analyse(root, index={
        "import_edges": {"mini/leaf.py": ["mini/secret.py"]}})
    facts = rep.get("mini/secret.py")
    assert facts.classification == "unknown", facts.reason
    assert "mini/leaf.py" not in facts.imported_by
    assert facts.entry == ""
    # and the disagreement is not swallowed either -- it is reported
    assert "mini/leaf.py -> mini/secret.py" in rep.index_extra_edges


def test_a_swallowed_importerror_is_not_evidence_WITH_AN_INDEX(tmp_path: Path):
    """CONFIGURATION: an index is supplied -- the shipped one, for the reason
    spelled out in the test above."""
    root = _mini(tmp_path, extra={"mini/secret.py": SECRET},
                 patch={"mini/leaf.py": '"""leaf."""\n\ntry:\n'
                                        "    from . import secret\n"
                                        "except ImportError:\n"
                                        "    secret = None\n\nLEAF = 1\n"})
    rep = analyse(root, index={
        "import_edges": {"mini/leaf.py": ["mini/secret.py"]}})
    facts = rep.get("mini/secret.py")
    assert facts.classification == "unknown", facts.reason
    assert "mini/leaf.py" not in facts.imported_by
    assert "mini/leaf.py -> mini/secret.py" in rep.index_extra_edges


def test_a_real_edge_the_index_also_has_is_not_a_disagreement(mini_repo: Path):
    """The rule has to admit the honest case or it is just a refusal: an index
    that agrees with the walk produces no finding at all.

    CONFIGURATION: an index is supplied, carrying an edge the walk found on its
    own (``mini/alpha.py -> mini/chain.py``)."""
    rep = analyse(mini_repo, index={
        "import_edges": {"mini/alpha.py": ["mini/chain.py"]}})
    assert rep.index_extra_edges == ()
    assert rep.get("mini/chain.py").classification == "reachable"


def test_an_import_whose_importerror_is_swallowed_is_not_evidence(tmp_path: Path):
    root = _mini(tmp_path, extra={"mini/secret.py": SECRET},
                 patch={"mini/leaf.py": '"""leaf."""\n\ntry:\n'
                                        "    from . import secret\n"
                                        "except ImportError:\n"
                                        "    secret = None\n\nLEAF = 1\n"})
    rep = analyse(root)
    facts = rep.get("mini/secret.py")
    assert facts.classification == "unknown", facts.reason
    assert any("ImportError" in e for e in facts.evidence)
    assert "mini/leaf.py" not in facts.imported_by


def test_the_fallback_import_inside_the_handler_is_real(tmp_path: Path):
    """``except ImportError: from . import secret`` is the import that ACTUALLY
    runs when the first one fails. Weakening it too would delete real edges."""
    root = _mini(tmp_path, extra={"mini/secret.py": SECRET},
                 patch={"mini/leaf.py": '"""leaf."""\n\ntry:\n'
                                        "    import nonexistent_third_party\n"
                                        "except ImportError:\n"
                                        "    from . import secret\n\nLEAF = 1\n"})
    rep = analyse(root)
    assert rep.get("mini/secret.py").classification == "reachable"
    assert "mini/leaf.py" in rep.get("mini/secret.py").imported_by


def test_a_try_that_does_not_catch_importerror_keeps_its_edges(tmp_path: Path):
    """The rule is narrow on purpose: only a handler that NAMES ImportError
    counts. ``except Exception`` around an import is too common a shape to
    reclassify on evidence that is not there."""
    root = _mini(tmp_path, extra={"mini/secret.py": SECRET},
                 patch={"mini/leaf.py": '"""leaf."""\n\ntry:\n'
                                        "    from . import secret\n"
                                        "except Exception:\n"
                                        "    secret = None\n\nLEAF = 1\n"})
    rep = analyse(root)
    assert rep.get("mini/secret.py").classification == "reachable"


def test_an_else_branch_of_if_false_is_still_live(tmp_path: Path):
    root = _mini(tmp_path, extra={"mini/secret.py": SECRET},
                 patch={"mini/leaf.py": '"""leaf."""\n\nif False:\n'
                                        "    pass\nelse:\n"
                                        "    from . import secret\n\nLEAF = 1\n"})
    rep = analyse(root)
    assert rep.get("mini/secret.py").classification == "reachable"


# ----------------------------------------------------- runs on this repo

def test_analyse_runs_on_this_repository():
    """Self-application: the engine must survive the tree it was written in.

    Asserted loosely on purpose -- pinning exact counts here would make an
    unrelated new module fail this test, and a gate that cries wolf gets
    disabled. The exact numbers belong in the generated report, which is
    diffed, not in an assertion."""
    root = Path(__file__).resolve().parents[1]
    rep = analyse(root)
    assert rep.counts["entry"] > 0
    assert rep.counts["reachable"] > rep.counts["island"]
    assert rep.get("daedalus/cli.py").classification == "entry"
    offload = rep.get("daedalus/offload.py")
    assert offload.classification in ("entry", "reachable")
    # web_api's route table must be visible, or the HTTP surface is dark
    assert any(e.kind == "http" and e.name.startswith("/api/")
               for e in rep.entry_points)
