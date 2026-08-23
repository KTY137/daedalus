"""Checks for the revision anchor.

Run directly::

    python -m pytest experiments/forest_v2/s02_types/test_revision_corpus.py

The module under test is the only part of this slice that shells a
subprocess, so most of what is checked here is the fence around that: the
read-only verb allowlist, the single writing function's refusal to overwrite,
and the cleanup of what it wrote.  The rest checks the property the anchor
exists for -- that reading a package tree out of git history gives the same
corpus, byte-for-byte after line-ending normalisation, as checking it out.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import revision_corpus as rc  # noqa: E402
import type_plane as tp  # noqa: E402

_PINNED: dict | None = None


def pinned_report() -> dict:
    """Building the plane over the kernel is the expensive part; do it once."""
    global _PINNED
    if _PINNED is None:
        _PINNED = rc.measure_at_revision()
    return _PINNED


# --------------------------------------------------------------------------
# the fence around the subprocess
# --------------------------------------------------------------------------
@pytest.mark.parametrize("verb", ["checkout", "commit", "push", "clean", "reset", "gc"])
def test_the_gate_refuses_every_verb_that_could_write(verb: str) -> None:
    """One door, and it is shut for anything that is not a read."""
    with pytest.raises(rc.RevisionUnavailable) as caught:
        rc._run(rc.REPO_ROOT, [verb])
    assert "read-only" in str(caught.value)


def test_the_gate_refuses_an_empty_command() -> None:
    with pytest.raises(rc.RevisionUnavailable):
        rc._run(rc.REPO_ROOT, [])


def test_the_allowlist_is_exactly_the_three_plumbing_reads() -> None:
    """Named so that widening it is a deliberate act with a red test attached."""
    assert set(rc._READ_ONLY_VERBS) == {"rev-parse", "ls-tree", "cat-file"}


def test_materialise_refuses_to_write_into_an_existing_directory(tmp_path: Path) -> None:
    """The one writing function may create, never overwrite."""
    dest = tmp_path / "already"
    dest.mkdir()
    with pytest.raises(rc.RevisionUnavailable) as caught:
        rc.materialise(rc.REPO_ROOT, rc.PINNED_REVISION, ("daedalus",), dest)
    assert "already exists" in str(caught.value)


def test_an_unknown_revision_is_named_not_swallowed() -> None:
    with pytest.raises(rc.RevisionUnavailable):
        rc.resolve(rc.REPO_ROOT, "0" * 40)


def test_the_scratch_tree_is_removed_even_when_the_body_raises() -> None:
    seen: list[Path] = []
    with pytest.raises(ZeroDivisionError):
        with rc.tree_at(rc.REPO_ROOT, rc.PINNED_REVISION, ("daedalus",)) as made:
            seen.append(Path(made["root"]))
            assert seen[0].is_dir()
            raise ZeroDivisionError("deliberate")
    assert not seen[0].exists()


# --------------------------------------------------------------------------
# the property the anchor exists for
# --------------------------------------------------------------------------
def test_the_pin_resolves_to_itself() -> None:
    assert rc.resolve(rc.REPO_ROOT, rc.PINNED_REVISION) == rc.PINNED_REVISION


def test_reading_history_reproduces_the_published_corpus() -> None:
    """Revision + digest + file count, all three.

    This is the whole repair in one assertion: the published numbers are now a
    function of a fixed input, so they are re-derivable from history alone on
    any clone that has the commit.
    """
    report = pinned_report()
    assert report["revision"] == rc.PINNED_REVISION
    assert report["corpus_pin"]["sha256"] == rc.PINNED_KERNEL_DIGEST
    assert report["corpus_pin"]["files"] == rc.PINNED_KERNEL_FILES
    assert report["functions_total"] == 4203


def test_the_published_root_names_the_revision_not_a_temp_directory() -> None:
    """A temp path in a published report makes the report unreproducible."""
    report = pinned_report()
    assert report["root"] == f"git:{rc.PINNED_REVISION[:12]}"
    assert report["revision_is_pinned"] is True


def test_only_python_files_are_materialised() -> None:
    """The frozen corpus must be the same *kind* of corpus as the live one.

    ``type_plane.iter_py_files`` walks ``*.py`` and nothing else, so pulling
    more out of history would silently compare two different file sets.
    """
    blobs = rc.list_python_blobs(rc.REPO_ROOT, rc.PINNED_REVISION, ("daedalus",))
    assert blobs
    assert all(path.endswith(".py") for path in blobs)
    assert all(path.startswith("daedalus/") for path in blobs)


def test_a_crlf_checkout_of_the_frozen_tree_pins_identically(tmp_path: Path) -> None:
    """Line endings are the trap, and the digest is normalised past it.

    History stores the kernel package with LF; a checkout on this platform can
    hand it back with CRLF.  If the pin were byte-exact the two would disagree
    on every file and the anchor would be useless off Linux.  Demonstrated
    rather than asserted in prose: materialise the frozen tree, rewrite every
    file to CRLF, and require the same digest out of both.
    """
    lf = tmp_path / "lf"
    rc.materialise(rc.REPO_ROOT, rc.PINNED_REVISION, ("daedalus",), lf)
    crlf = tmp_path / "crlf"
    for src in sorted(lf.rglob("*.py")):
        target = crlf / src.relative_to(lf)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(src.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))

    def pin_of(root: Path) -> dict:
        # the pin, not the whole plane: parsing the kernel twice more to learn
        # something about byte-level encoding would be a slow way to ask
        entries = [
            (path.relative_to(root).as_posix(), path.read_bytes())
            for path in tp.iter_py_files(root, ("daedalus",))
        ]
        return tp.corpus_pin(entries)

    from_lf, from_crlf = pin_of(lf), pin_of(crlf)
    assert from_lf["files"] == from_crlf["files"] == rc.PINNED_KERNEL_FILES
    assert from_lf == from_crlf
    assert from_lf["sha256"] == rc.PINNED_KERNEL_DIGEST
