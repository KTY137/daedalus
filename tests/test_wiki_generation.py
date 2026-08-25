"""The deterministic halves of wiki generation, and the write root they honour.

``plan`` and ``verify`` are the parts of automatic wiki generation that decide
things without a model, so they are the parts that must be tested. Several of
the tests below exist because of a measured defect (2026-08-25): both ``main``
functions took ``argv[1]`` as a repository root without looking at it, and
``plan`` then ran ``mkdir(parents=True)`` under it. Running
``python -m daedalus.wiki.plan --help`` therefore created a directory literally
named ``--help`` in the repository and wrote a plan into it -- an argv-driven
write root, which is what invariant 8 (bounded effects) exists to prevent.
"""

from __future__ import annotations

import pathlib

import pytest

from daedalus.wiki import plan as wp
from daedalus.wiki import verify as wv

MODULE_SOURCE = "\n".join([
    "def compute_total(rows):",
    "    return sum(rows)",
    "",
    "",
    "class ThingMaker:",
    "    def build_it(self):",
    "        return compute_total([1, 2])",
    "",
])


def _write(path: pathlib.Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")


def _padding(prefix: str, count: int) -> str:
    """Filler definitions, so a fixture can clear plan's size thresholds.

    ``survey`` ignores a directory with fewer than ``MIN_BUCKET_FILES`` files or
    fewer than ``MIN_BUCKET_LOC`` lines -- a wiki page about a two-line package
    is not worth an author. A fixture that wants a topic has to be big enough
    to deserve one.
    """
    out = []
    for i in range(count):
        out += [f"def {prefix}_step_{i}(value):", f"    return value + {i}", "", ""]
    return "\n".join(out)


def _repo(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "mod_one.py").write_text(
        MODULE_SOURCE + _padding("one", 40), encoding="utf-8", newline="")
    (root / "pkg" / "mod_two.py").write_text(
        _padding("two", 40), encoding="utf-8", newline="")
    (root / "docs" / "wiki").mkdir(parents=True)
    return root


@pytest.mark.parametrize("flag", ["--help", "-h", "--out=/tmp/x"])
@pytest.mark.parametrize("mod", [wp, wv])
def test_a_flag_is_never_taken_for_a_repository_root(mod, flag, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert mod.main(["prog", flag]) == 2
    capsys.readouterr()
    assert list(tmp_path.iterdir()) == [], "a flag must not create anything on disk"


@pytest.mark.parametrize("mod", [wp, wv])
def test_a_root_that_does_not_exist_is_refused_rather_than_created(mod, tmp_path, capsys):
    missing = tmp_path / "not" / "there"
    assert mod.main(["prog", str(missing)]) == 2
    assert "not a directory" in capsys.readouterr().out
    assert not missing.exists(), "a missing root must be refused, not made"


@pytest.mark.parametrize("mod", [wp, wv])
def test_no_argument_prints_usage(mod, capsys):
    assert mod.main(["prog"]) == 2
    assert "usage:" in capsys.readouterr().out


def test_plan_surveys_the_tree_and_hands_every_author_a_prompt(tmp_path):
    root = _repo(tmp_path)
    built = wp.build_plan(root, authors=1, wiki_dir="docs/wiki")
    assert built["topics"], "a tree with a package must produce at least one topic"
    assert built["authors"] == len(built["tasks"]) == 1
    task = built["tasks"][0]
    assert "pkg/mod_one.py" in task["files"]
    assert "compute_total" in task["prompt"], "the prompt must name real symbols"


def test_a_package_too_small_to_deserve_a_page_produces_no_topic(tmp_path):
    root = tmp_path / "tiny"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "only.py").write_text(MODULE_SOURCE, encoding="utf-8", newline="")
    assert wp.survey(root) == [], "one short file is not a topic"


def test_the_wiki_is_not_read_into_the_vocabulary_that_judges_the_wiki(tmp_path):
    """The page under verification must not be its own evidence.

    ``tree_vocabulary`` walks the whole tree, and a wiki normally sits inside
    the tree it describes. Before 2026-08-25 it was not excluded, so a symbol
    a model invented occurred in the page, entered the vocabulary, and thereby
    proved itself real -- ``unknown_symbol`` could not fire on an invented name
    at all. That is a candidate supplying its own judge (invariant 4).
    """
    root = _repo(tmp_path)
    wiki = root / "docs" / "wiki"
    invented = "absent_helper"
    _write(wiki / "pkg-index.md", [
        "# pkg",
        "",
        f"The module exposes `{invented}`, which is mentioned here and only here.",
        "",
        f"Another paragraph naming {invented} again, in plain prose this time.",
    ])
    assert invented not in (root / "pkg" / "mod_one.py").read_text(encoding="utf-8")
    report = wv.verify(root, wiki)
    unknown = [f["detail"] for f in report["findings"].get("unknown_symbol", [])]
    assert invented in unknown, "a name only the wiki knows is not a name the tree has"


def test_verify_fails_a_page_that_claims_what_the_tree_does_not_contain(tmp_path):
    root = _repo(tmp_path)
    wiki = root / "docs" / "wiki"
    _write(wiki / "pkg-index.md", [
        "# pkg",
        "",
        "See [the module](../../pkg/mod_one.py) and [the ghost](../../pkg/gone.py).",
        "",
        "It calls `compute_total` and also `absent_helper`.",
    ])
    report = wv.verify(root, wiki)
    kinds = report["findings_by_kind"]
    assert kinds.get("broken_link") == 1
    assert kinds.get("unknown_symbol") == 1
    assert report["verdict"] == "FAIL"
    unknown = [f["detail"] for f in report["findings"]["unknown_symbol"]]
    assert unknown == ["absent_helper"]


def test_verify_passes_a_page_whose_every_claim_is_in_the_tree(tmp_path):
    root = _repo(tmp_path)
    wiki = root / "docs" / "wiki"
    _write(wiki / "pkg-index.md", [
        "# pkg",
        "",
        "The module is [pkg/mod_one.py](../../pkg/mod_one.py).",
        "",
        "It defines `compute_total` and `ThingMaker`.",
    ])
    _write(wiki / "pkg-detail.md", [
        "# detail",
        "",
        "[back](pkg-index.md) -- `compute_total` is used by `ThingMaker`.",
    ])
    report = wv.verify(root, wiki)
    assert report["findings_by_kind"].get("broken_link", 0) == 0
    assert report["findings_by_kind"].get("unknown_symbol", 0) == 0
    assert report["verdict"] == "PASS"
    assert report["modules_linked_from_wiki"] == 1


def test_an_external_claim_without_a_url_is_a_finding(tmp_path):
    root = _repo(tmp_path)
    wiki = root / "docs" / "wiki"
    _write(wiki / "pkg-index.md", [
        "# pkg",
        "",
        "> **Extern:** every graph database stores edges as adjacency lists.",
        "",
        "The module is [pkg/mod_one.py](../../pkg/mod_one.py).",
    ])
    report = wv.verify(root, wiki)
    assert report["findings_by_kind"].get("unsourced_claim") == 1
    assert report["verdict"] == "FAIL"
