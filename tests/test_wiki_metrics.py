"""Tests for ``daedalus.wiki.metrics`` -- the health instrument of the wiki.

Until 2026-09-05 this module had no test of its own (the wiki page about
``daedalus/wiki`` measured that). Three things are worth pinning:

* the walk leaves out what is not this project's structure -- a nested git
  checkout AND a frozen application bundle -- and SAYS so in
  ``could_not_measure`` instead of silently reading a copy of the tree as its
  health;
* ``wiki_health`` on a tiny real tree returns the documented shape, and a
  doc->source edge that the wiki asserts is counted as a cross-plane edge;
* a root that is not a directory is reported as "nothing was walked", never
  as an empty tree.
"""

from __future__ import annotations

import pathlib

from daedalus.wiki import metrics as wiki_metrics


def _write(root: pathlib.Path, rel: str, text: str) -> pathlib.Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _tiny_tree(root: pathlib.Path) -> None:
    _write(root, "pkg/__init__.py", "")
    _write(root, "pkg/widget.py",
           "class Widget:\n    def render(self):\n        return 1\n")
    _write(root, "docs/wiki/widget.md",
           "# Widget\n\n`Widget` lives in [widget.py](../../pkg/widget.py).\n")


def test_health_reports_the_documented_shape_on_a_tiny_tree(tmp_path: pathlib.Path) -> None:
    _tiny_tree(tmp_path)
    report = wiki_metrics.wiki_health(tmp_path)
    for key in ("metrics_version", "entities", "triples", "crossplane_edges",
                "crossplane_survival_rate", "could_not_measure", "planes"):
        assert key in report, key
    assert report["crossplane_edges"] >= 1, report
    assert report["triples"] > 0


def test_a_missing_root_is_not_an_empty_tree(tmp_path: pathlib.Path) -> None:
    report = wiki_metrics.wiki_health(tmp_path / "does-not-exist")
    assert report["triples"] == 0
    assert any("nothing was walked" in line for line in report["could_not_measure"]), (
        report["could_not_measure"])


def test_a_nested_checkout_is_left_out_and_named(tmp_path: pathlib.Path) -> None:
    _tiny_tree(tmp_path)
    _write(tmp_path, "nested/.git", "gitdir: /elsewhere\n")
    _write(tmp_path, "nested/pkg/copy_widget.py", "class CopyWidget:\n    pass\n")
    report = wiki_metrics.wiki_health(tmp_path)
    assert not any("copy_widget" in str(t) for t in wiki_metrics.extract_graph(tmp_path))
    assert any("nested git checkout" in line for line in report["could_not_measure"]), (
        report["could_not_measure"])


def test_a_frozen_bundle_is_left_out_and_named(tmp_path: pathlib.Path) -> None:
    """MEASURED 2026-09-05: two PyInstaller copies of ``daedalus`` under
    ``apps/web/src-tauri`` were walked as project structure by every wiki
    instrument. The marker is ``_internal/base_library.zip``; the positive
    control removes it and the copy is walked again."""
    _tiny_tree(tmp_path)
    _write(tmp_path, "apps/desktop/backend/_internal/base_library.zip", "PK")
    _write(tmp_path, "apps/desktop/backend/_internal/pkg/frozen_widget.py",
           "class FrozenWidget:\n    pass\n")
    report = wiki_metrics.wiki_health(tmp_path)
    assert not any("frozen_widget" in str(t) for t in wiki_metrics.extract_graph(tmp_path))
    assert any("frozen application bundle" in line for line in report["could_not_measure"]), (
        report["could_not_measure"])

    (tmp_path / "apps/desktop/backend/_internal/base_library.zip").unlink()
    assert any("frozen_widget" in str(t) for t in wiki_metrics.extract_graph(tmp_path)), (
        "the fixture's bundle module was never walked; the exclusion above was vacuous")
