"""The reachability walk honours the repo's declared project scope.

WHY THIS PACKET EXISTS (G1-MAP-02). ``daedalus map --check`` fails at HEAD with
1348 drift rows, and 91% of them are not this project's code `[MEASURED
2026-09-03]`: 1082 from ``runs/`` (run artifacts), 148 from
``apps/web/src-tauri/backend/_internal/`` (gitignored Tauri build output, a
verbatim copy of the package) and 11 from ``vault/`` (the Obsidian knowledge
vault). The 87 rows that are actually about ``daedalus/`` are buried under
them, so the gate that exists to say what drifted cannot be read.

THIS IS A KNOWN REGRESSION, NOT AN OVERSIGHT. ``daedalus/mapping/drift.py``
says so in its own prose: *"``DAEDALUS_IGNORE`` and ``.daedalusignore`` narrow
the structural index. Since the gate now reads the tree through
:mod:`~daedalus.mapping.reach`, which walks the filesystem itself, they cannot
narrow what the gate sees."* The declaration exists and is correct --
``.daedalusignore`` already carries ``center: daedalus, tools, apps/web/src``
and ignores ``runs/`` and ``vault/`` -- and the engine that now does the walking
simply never asks.

THE FIX FOLLOWS THE DOCTRINE ALREADY WRITTEN, in
``daedalus/structcore/ignore.py:ProjectScope``: a file outside the center is
SHELL -- *"still indexed and still resolvable as an import target, so edges
pointing at it stay true, but withheld from every metric"*. So reach keeps
walking and resolving everything, which is what makes an edge from center code
into a thirdpartyed tree stay honest; it only learns to MARK the periphery, and the
consumers that compute metrics do the withholding.

WHAT THIS DELIBERATELY DOES NOT DO. It does not narrow the walk. Dropping files
from the walk would make an import that points into ``runs/`` resolve to
nothing, turning a true edge into a missing one -- the silent direction of error
this engine's docstring calls worse than a false island. It also does not add a
``shell`` classification: a shell module still IS an island or reachable or a
shim, and conflating "where does it live" with "can anything get to it" would
lose one of the two answers.
"""
from __future__ import annotations

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
    """Only the COMMITTED declaration may say what is periphery.

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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "FINDING 2026-09-03: the `center:` directive in .daedalusignore is "
        "INERT. Nothing parses it -- `project_scope` takes its center from an "
        "explicit argument or DAEDALUS_CENTER only, and `_parse_line` turns "
        "the line into an ignore pattern that matches nothing. This repo's "
        "own .daedalusignore declares `center: daedalus, tools, apps/web/src` "
        "with the comment 'Weakest tier: an explicit --center or "
        "DAEDALUS_CENTER still overrides', which describes a precedence that "
        "was never implemented. Fixing it changes structcore's metric and "
        "naming semantics repo-wide, so it is a separate packet and not this "
        "one; pinned here so the gap cannot be forgotten."
    ),
)
def test_the_center_directive_in_the_ignore_file_is_read(repo: Path) -> None:
    assert analyse(repo).scope["center"] == ["mini"]


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
