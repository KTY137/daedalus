"""Declared census periphery stays resolved but is excluded from rankings.

Ported from MAP-02; historical measurement prose remains on the source branch.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from daedalus.mapping import analyse


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

DAEDALUSIGNORE = """\
# the project is mini/; everything else in this repo is periphery
center: mini

# not this project's code
runs/
thirdparty/
"""

FILES = {
    "pyproject.toml": PYPROJECT,
    ".daedalusignore": DAEDALUSIGNORE,
    # --- the center -------------------------------------------------------
    "mini/__init__.py": "",
    "mini/cli.py": (
        "from mini.core import work\n"
        "from thirdparty.helper import assist\n"
        "\n"
        "def main():\n"
        "    return work(), assist()\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n"
    ),
    "mini/core.py": "def work():\n    return 1\n",
    # a REAL island, inside the center: this is the row the gate must keep.
    # It imports something, so it is an island rather than an ``orphan`` --
    # the engine separates "reaches nothing and is reached by nothing" from
    # "reaches things, but nothing reaches it", and this packet is about the
    # second.
    "mini/stranded.py": (
        "from mini.core import work\n"
        "\n"
        "def nobody_calls_me():\n"
        "    return work() + 1\n"
    ),
    # --- the shell --------------------------------------------------------
    # imported BY the center, so its edge must survive the change
    "thirdparty/__init__.py": "",
    "thirdparty/helper.py": "def assist():\n    return 3\n",
    # an island, but periphery: the gate must NOT rank this as project drift
    "thirdparty/unused.py": "def spare():\n    return 4\n",
    "runs/artifact_script.py": "print('a run artifact, not source')\n",
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


# ------------------------------------------------------- the shell is marked

def test_project_code_is_not_shell(repo: Path) -> None:
    report = analyse(repo)
    for module in ("mini/cli.py", "mini/core.py", "mini/stranded.py"):
        assert _facts(report, module).shell is False, module


def test_an_ignored_directory_is_shell(repo: Path) -> None:
    report = analyse(repo)
    for module in ("thirdparty/helper.py", "thirdparty/unused.py",
                   "runs/artifact_script.py"):
        assert _facts(report, module).shell is True, module


def test_the_environment_cannot_make_a_module_periphery(
    repo: Path, monkeypatch,
) -> None:
    """Only the repository declaration may say what is periphery.

    ``tests/test_mapping_drift.py`` already pins that no environment variable
    may hide a module from the gate, and that rule is why this marking reads
    ``.daedalusignore`` directly instead of ``project_scope`` (which folds in
    ``DAEDALUS_IGNORE`` and ``DAEDALUS_CENTER``). A scope an env var can widen
    is a gate anyone can silence without leaving a diff.
    """
    monkeypatch.setenv("DAEDALUS_IGNORE", "stranded.py")
    monkeypatch.setenv("DAEDALUS_CENTER", "thirdparty")
    report = analyse(repo)
    assert _facts(report, "mini/stranded.py").shell is False
    assert _facts(report, "thirdparty/unused.py").shell is True


def test_reach_deliberately_does_not_apply_the_declared_center(
    repo: Path,
) -> None:
    """The census keeps covering the whole repository.

    G1-MAP-03 made the ``center:`` directive live -- ``project_scope`` reads it
    now (``tests/test_structcore_center_directive.py``). Reach still passes an
    explicit empty center, which is the strongest tier of that precedence, so
    the directive does not reach it.

    That is a decision, not an omission. This repo declares
    ``center: daedalus, tools, apps/web/src``; honouring it here would make
    ``scripts/`` and ``experiments/`` periphery and withhold them from the
    island census -- and ``scripts/fourfold_repo_probe.py`` is exactly the
    operator entry point whose absence from an earlier survey produced a false
    island (§4.1 of docs/G1_LOOSE_PARTS_SURVEY_20260903.md). What is periphery
    for a hotspot ranking is not automatically periphery for "can anything
    reach this at all". Only the committed ignore rules narrow this census.
    """
    assert analyse(repo).scope["center"] == []
    assert _facts(analyse(repo), "mini/stranded.py").shell is False


# --------------------------------------------- the walk is NOT narrowed

def test_shell_modules_are_still_walked_and_still_classified(repo: Path) -> None:
    """Marking is not dropping. Every periphery file keeps its row."""
    report = analyse(repo)
    for module in ("thirdparty/helper.py", "thirdparty/unused.py",
                   "runs/artifact_script.py"):
        facts = _facts(report, module)
        assert facts.classification in {
            "reachable", "entry", "island", "shim", "unknown", "orphan", "test",
        }, facts.classification


def test_an_edge_from_the_center_into_the_shell_stays_true(repo: Path) -> None:
    """The reason the walk must not be narrowed.

    ``mini/cli.py`` imports ``thirdparty.helper``. Dropping the shell from the walk
    would leave that import resolving to nothing -- a true edge silently
    becoming a missing one.
    """
    report = analyse(repo)
    assert _facts(report, "thirdparty/helper.py").classification == "reachable"
    assert "mini/cli.py" in _facts(report, "thirdparty/helper.py").imported_by


def test_a_real_island_inside_the_center_is_still_an_island(repo: Path) -> None:
    """The signal the noise was burying."""
    assert _facts(analyse(repo), "mini/stranded.py").classification == "island"


# ----------------------------------------- a narrowed run stays distinguishable

def test_the_report_records_the_scope_it_ran_under(repo: Path) -> None:
    """Doctrine borrowed from the drift gate: a run that looks at the tree
    differently must never be indistinguishable from one that did not."""
    scope = analyse(repo).scope
    assert scope["fingerprint"]
    patterns = scope["ignore_patterns"]
    assert isinstance(patterns, list)
    assert any("runs" in str(p) for p in patterns)


def test_scope_survives_to_dict(repo: Path) -> None:
    payload = analyse(repo).to_dict()
    assert payload["scope"]["fingerprint"]
    row = next(m for m in payload["modules"] if m["module"] == "thirdparty/unused.py")
    assert row["shell"] is True


def test_two_runs_over_an_unchanged_tree_are_identical(repo: Path) -> None:
    """The property the whole artifact rests on, re-pinned with the new field."""
    assert analyse(repo).to_json() == analyse(repo).to_json()


def test_an_undeclared_center_leaves_everything_in_the_core(tmp_path: Path) -> None:
    """No ``.daedalusignore`` means the whole repo is the project, which is the
    historical behaviour every unconfigured repo must keep getting."""
    for rel, text in FILES.items():
        if rel == ".daedalusignore":
            continue
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    report = analyse(tmp_path)
    assert _facts(report, "thirdparty/unused.py").shell is False
    assert report.scope["ignore_patterns"] == []


# ------------------------------------------- the gate withholds the periphery

def test_the_gate_does_not_rank_periphery_islands_as_project_drift(
    repo: Path,
) -> None:
    """``thirdparty/unused.py`` is an island, and it is not this project's
    problem. ``mini/stranded.py`` is an island, and it is."""
    from daedalus.mapping import drift as drift_mod

    scan = drift_mod.scan(repo)
    assert "mini/stranded.py" in scan.state["islands"]
    assert "thirdparty/unused.py" not in scan.state["islands"]
    assert "runs/artifact_script.py" not in scan.state["modules"]


def test_the_gate_reports_how_much_it_withheld(repo: Path) -> None:
    """Never silently less coverage: the count of periphery rows is stated."""
    from daedalus.mapping import drift as drift_mod

    counts = drift_mod.scan(repo).state["counts"]
    assert counts["shell_withheld"] > 0


def test_mixed_and_unknown_disagreements_remain_visible(repo: Path) -> None:
    from daedalus.mapping import drift

    visible = (
        "mini/core.py -> mini/stranded.py",
        "mini/core.py -> thirdparty/helper.py",
        "thirdparty/helper.py -> mini/core.py",
        "thirdparty/helper.py -> absent.py",
        "unparsed disagreement",
    )
    shell_only = "thirdparty/helper.py -> thirdparty/unused.py"
    report = replace(analyse(repo), index_extra_edges=(*visible, shell_only))
    scan = drift.scan(repo, reach_report=report)
    assert scan.state["index_extra_edges"] == sorted(visible)
    assert scan.state["counts"]["index_extra_edges"] == len(visible)


def test_inventory_withholds_shell_without_changing_reach_evidence(repo: Path) -> None:
    from daedalus.mapping import inventory, switches

    report = analyse(repo)
    doc = inventory.build(
        repo, reports=(report, switches.analyse(repo)),
        head="fixture", branch="fixture", dirty=False,
    )
    ranked = {
        feature["module"]
        for area in doc["areas"] for feature in area["features"]
        if feature.get("module")
    }
    assert "mini/stranded.py" in ranked
    assert "thirdparty/unused.py" not in ranked
    assert "thirdparty/helper.py" not in ranked
    assert report.get("thirdparty/helper.py").classification == "reachable"
    withheld = [row for row in report.modules if row.shell and row.classification != "test"]
    assert doc["counts"]["shell_withheld"] == len(withheld) > 0


def test_periphery_read_change_has_a_distinct_scope_fingerprint(repo: Path) -> None:
    before = analyse(repo)
    (repo / ".daedalusignore").write_text("thirdparty/\n", encoding="utf-8")
    after = analyse(repo)
    assert before.scope["fingerprint"] != after.scope["fingerprint"]
    assert before.get("runs/artifact_script.py").shell is True
    assert after.get("runs/artifact_script.py").shell is False
    assert {row.module for row in before.modules} == {row.module for row in after.modules}


# --------------------------------------------------- the tree this was found in

def test_the_real_repo_marks_its_declared_periphery() -> None:
    """Regression pin against the actual checkout, not a fixture."""
    report = analyse(Path(__file__).resolve().parents[1])
    shell_prefixes = ("runs/", "vault/", "apps/web/src-tauri/backend/_internal/",
                      "daedalus/eval/fixtures/")
    for facts in report.modules:
        if facts.module.startswith(shell_prefixes):
            assert facts.shell is True, facts.module
        elif facts.module.startswith("daedalus/"):
            # Product code is never periphery. ``daedalus/eval/fixtures/`` is
            # the one declared exception above: a corpus the evaluator runs on.
            assert facts.shell is False, facts.module
