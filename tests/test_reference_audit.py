"""Every case here is a reference shape MEASURED in a 2026-07-30 advisory run.

The four-tier funnel over this repository cited 77 paths in its planning tier
and 42 of them did not resolve. Splitting those 42 was the whole result: 19
were a real file with its directory dropped, 1 was a basename shared by two
files, and 22 named a file that exists nowhere under any path. The three need
opposite responses -- repair, refuse to guess, discard -- and a checker that
reports one number for all of them is worth very little.

So these tests pin the SPLIT, not the total.
"""
from __future__ import annotations

import pytest

from daedalus.lanes.grounding import audit_references


@pytest.fixture
def repo(tmp_path):
    """A miniature tree with the shapes the real audit has to separate."""
    files = {
        "daedalus/spine/attempt.py": "def run_attempt():\n    pass\n",
        "daedalus/spine/ledger.py": "class Ledger:\n    def append(self):\n        pass\n",
        "daedalus/observe/shape.py": "def _human_bytes(n):\n    return str(n)\n",
        "daedalus/council/vendors.py": "def dispatch():\n    pass\n",
        # same basename in two places: unresolvable without guessing
        "daedalus/eval/__init__.py": "",
        "tools/__init__.py": "",
    }
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path, tuple(files)


def audit(text, repo):
    root, tracked = repo
    return audit_references(text, tracked, root)


def test_exact_path_resolves(repo):
    a = audit("see daedalus/spine/attempt.py for the runner", repo)
    assert a.cited == 1 and a.resolved == 1
    assert a.rate == 1.0 and a.invented == ()


def test_stripped_directory_is_repaired_not_invented(repo):
    # MEASURED: the plan tier wrote daedalus/attempt.py, daedalus/ledger.py and
    # daedalus/killswitch.py for files that live under daedalus/spine/. The
    # finding behind such a citation is often real; only the path is wrong.
    a = audit("fix daedalus/attempt.py and daedalus/ledger.py", repo)
    assert a.invented == ()
    assert dict(a.repaired) == {
        "daedalus/attempt.py": "daedalus/spine/attempt.py",
        "daedalus/ledger.py": "daedalus/spine/ledger.py",
    }
    assert a.resolved == 2


def test_file_absent_under_every_name_is_invented(repo):
    # MEASURED: daedalus/runner.py, daedalus/spine/anchor.py and
    # daedalus/spine/chain.py were named by the plan tier and exist nowhere.
    a = audit("patch daedalus/runner.py and daedalus/spine/chain.py", repo)
    assert sorted(a.invented) == ["daedalus/runner.py", "daedalus/spine/chain.py"]
    assert a.repaired == () and a.resolved == 0
    assert a.invention_rate == 1.0


def test_shared_basename_is_ambiguous_and_never_guessed(repo):
    # `__init__.py` exists twice, so the basename repair that fixes a stripped
    # directory cannot be applied here without picking one at random. MEASURED:
    # 1 of the plan tier's 42 unresolvable paths was this shape, and guessing
    # would have produced a confidently wrong file.
    a = audit("look at daedalus/__init__.py", repo)
    assert a.ambiguous == ("daedalus/__init__.py",)
    # neither credited nor condemned: the audit cannot tell, and says so
    assert a.resolved == 0 and a.invented == ()


def test_symbol_missing_from_a_real_file_is_reported(repo):
    # MEASURED: _human_bytes was blamed on council/vendors.py while it lives in
    # observe/shape.py. The path resolved; the attribution was still wrong, and
    # that is a different failure from an invented path.
    a = audit("daedalus/council/vendors.py:_human_bytes is broken", repo)
    assert a.absent_symbols == (("daedalus/council/vendors.py", "_human_bytes"),)
    assert a.invented == () and a.resolved == 0


def test_nested_method_resolves(repo):
    # A top-level-only reading would call every method in the repository
    # absent; the funnel cited events.py:TransportRecord.from_dict and similar
    # throughout.
    a = audit("daedalus/spine/ledger.py:Ledger.append appends", repo)
    assert a.absent_symbols == () and a.resolved == 1


def test_paths_outside_the_repository_are_not_judged(repo):
    # MEASURED: an unanchored version reported the docstring example a/b.py,
    # the runtime path RUN_DIR/last_report.json and the written type
    # Any/typing.Any as invented files. None of them claims to be a file here.
    a = audit(
        "for example a/b.py; writes RUN_DIR/last_report.json; see Any/typing.Any",
        repo)
    assert a.cited == 0
    assert a.invented == () and a.rate == 0.0


def test_a_reference_repeated_is_counted_once(repo):
    a = audit("daedalus/runner.py " * 5, repo)
    assert a.cited == 1 and a.invented == ("daedalus/runner.py",)


def test_untracked_file_on_disk_does_not_launder_a_citation(repo):
    """The file list is authoritative, not the filesystem.

    A scratch file a contributor never committed must not make an invented
    citation look grounded -- that is why the audit takes `git ls-files` output
    rather than walking the tree.
    """
    root, tracked = repo
    (root / "daedalus" / "scratch.py").write_text("x = 1\n", encoding="utf-8")
    a = audit_references("daedalus/scratch.py leaks", tracked, root)
    assert a.invented == ("daedalus/scratch.py",)


def test_namespace_package_is_a_module_that_exists(tmp_path):
    """A directory without __init__.py still imports (PEP 420).

    MEASURED 2026-07-30: the write gate reported "module 'tools' does not
    exist" for a committed file that imports it, failing its own
    `test_no_false_positives_across_the_real_tree` with the message "this gate
    must never refuse real repo code". `tools` and `tests` are implicit
    namespace packages here -- both import fine and report __file__ is None.
    """
    from daedalus.lanes.checks import _module_path, unresolved_first_party_imports

    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "guard.py").write_text("def check():\n    pass\n",
                                                 encoding="utf-8")
    (tmp_path / "data").mkdir()          # a directory with no python in it
    (tmp_path / "data" / "rows.csv").write_text("a,b\n", encoding="utf-8")

    assert _module_path(tmp_path, "tools") == tmp_path / "tools"
    assert _module_path(tmp_path, "tools.guard") == tmp_path / "tools" / "guard.py"
    # a data folder must not launder an import that would fail at runtime
    assert _module_path(tmp_path, "data") is None

    assert unresolved_first_party_imports(
        "import tools\nfrom tools import guard\n", str(tmp_path),
        roots=("tools", "daedalus")) == []
    # and the invented import it exists to catch is still refused
    assert unresolved_first_party_imports(
        "import tools.invented\n", str(tmp_path),
        roots=("tools", "daedalus")) == ["module 'tools.invented' does not exist"]


def test_audit_is_serialisable(repo):
    a = audit("daedalus/attempt.py and daedalus/runner.py", repo)
    body = a.to_dict()
    assert body["cited"] == 2
    assert body["invented"] == ["daedalus/runner.py"]
    assert body["repaired"] == [["daedalus/attempt.py", "daedalus/spine/attempt.py"]]
