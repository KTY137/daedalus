"""Checks for the symbol-level task set builder.

Hermetic: builds a throwaway git repository per test rather than reading a
subject corpus, so these run anywhere and assert behaviour rather than a
measurement. The measured numbers for `black` live in the packet and the
result document, stamped with their anchor.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s09_eval import symbols, taskset_symbol  # noqa: E402

ANNOTATED = '''
def kept(x: int) -> int:
    return x + 1


class Holder:
    def method(self, y: str) -> None:
        pass
'''

ANNOTATED_EDITED = '''
def kept(x: int) -> int:
    return x + 99


class Holder:
    def method(self, y: str) -> None:
        pass
'''

WITH_NEW_SYMBOL = ANNOTATED_EDITED + '''

def freshly_added(z: int) -> int:
    return z
'''


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "subject"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    (root / "mod.py").write_text(ANNOTATED, encoding="utf-8")
    (root / "README.md").write_text("# start\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial commit")
    return root


def _commit(repo: Path, message: str, **files: str) -> None:
    for name, body in files.items():
        (repo / name.replace("__", ".")).write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


# --------------------------------------------------------------------------
# A3 / A4: gold is retrievable from the pre-image, and nothing leaks from after
# --------------------------------------------------------------------------
def test_gold_is_a_subset_of_the_parent_tree_symbols(repo: Path) -> None:
    _commit(repo, "adjust the kept helper", mod__py=ANNOTATED_EDITED,
            README__md="# start\n\nnow documented\n")

    record = taskset_symbol.build_record(repo, "HEAD", limit=10)
    assert record["statistics"]["cases"] == 1
    case = record["cases"][0]

    parent_symbols = symbols.symbol_table(ANNOTATED)
    for key in case["gold"]:
        path, _, qualname = key.partition("#")
        assert path == "mod.py"
        assert qualname in parent_symbols, f"{key} is not retrievable from the pre-image"


def test_a_symbol_created_by_the_commit_is_never_gold(repo: Path) -> None:
    _commit(repo, "add a helper and a note", mod__py=WITH_NEW_SYMBOL,
            README__md="# start\n\nnote\n")

    record = taskset_symbol.build_record(repo, "HEAD", limit=10)
    case = record["cases"][0]

    assert "mod.py#freshly_added" not in case["gold"]
    # Counted, not silently discarded.
    assert "mod.py#freshly_added" in case["gold_created_dropped"]


def test_a_commit_whose_only_symbol_is_new_is_excluded_and_counted(
    tmp_path: Path,
) -> None:
    root = tmp_path / "fresh"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    (root / "README.md").write_text("# start\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    _commit(root, "introduce a module and a note", mod__py=ANNOTATED,
            README__md="# start\n\nnote\n")

    record = taskset_symbol.build_record(root, "HEAD", limit=10)
    assert record["statistics"]["cases"] == 0
    assert record["exclusions"]["no_retrievable_gold_in_pre_image"]["count"] == 1


# --------------------------------------------------------------------------
# A6: every commit lands in exactly one bucket
# --------------------------------------------------------------------------
def test_the_exclusion_tally_accounts_for_every_commit(repo: Path) -> None:
    _commit(repo, "code only, no other plane", mod__py=ANNOTATED_EDITED)
    _commit(repo, "docs only", README__md="# start\n\nmore\n")
    _commit(repo, "cross plane", mod__py=WITH_NEW_SYMBOL,
            README__md="# start\n\nmore still\n")

    record = taskset_symbol.build_record(repo, "HEAD", limit=50)
    accounted = record["statistics"]["cases"] + sum(
        entry["count"] for entry in record["exclusions"].values()
    )
    assert accounted == record["statistics"]["commits_read"]


def test_a_code_only_commit_is_excluded_as_not_cross_plane(repo: Path) -> None:
    _commit(repo, "code only", mod__py=ANNOTATED_EDITED)
    record = taskset_symbol.build_record(repo, "HEAD", limit=10)
    assert record["exclusions"]["not_cross_plane"]["count"] == 1


def test_a_reformat_is_not_a_case(repo: Path) -> None:
    reformatted = ANNOTATED.replace("    return x + 1", "\n    return x  +  1")
    _commit(repo, "reformat and touch docs", mod__py=reformatted,
            README__md="# start\n\nreflow\n")
    record = taskset_symbol.build_record(repo, "HEAD", limit=10)
    assert record["statistics"]["cases"] == 0
    assert record["exclusions"]["no_symbol_changed"]["count"] == 1


# --------------------------------------------------------------------------
# A7: determinism
# --------------------------------------------------------------------------
def test_two_builds_are_identical(repo: Path) -> None:
    _commit(repo, "adjust and document", mod__py=ANNOTATED_EDITED,
            README__md="# start\n\ndocumented\n")
    first = taskset_symbol.build_record(repo, "HEAD", limit=10)
    second = taskset_symbol.build_record(repo, "HEAD", limit=10)
    assert first == second


# --------------------------------------------------------------------------
# leakage control: the symbol's own name is scrubbed from the query
# --------------------------------------------------------------------------
def test_the_scrub_removes_the_symbol_name_not_only_the_path(repo: Path) -> None:
    _commit(repo, "kept now returns 99", mod__py=ANNOTATED_EDITED,
            README__md="# start\n\nnote\n")
    record = taskset_symbol.build_record(repo, "HEAD", limit=10)
    case = record["cases"][0]

    assert "mod.py#kept" in case["gold"]
    assert "kept" in case["query_raw"]
    assert "kept" not in case["query_scrubbed"].split()
    assert "kept" in case["leak_tokens"]
