"""The primary-checkout write fence: a write aimed at the checkout is refused,
the SAME write aimed at a worktree is allowed.

LANDS AT: tests/test_primary_tree_fence.py

Every fence test here is PAIRED. A blocked-only assertion passes just as well
when the predicate is ``return "no"`` for everything, which is a guard that is
broken in the direction nobody notices until the product stops working; and an
allowed-only assertion passes when the predicate is ``return None``. So each
case states both halves against the same input shape.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.primary_tree import (            # noqa: E402
    PrimaryCheckoutWrite,
    assert_write_allowed,
    nearest_existing,
    overlap_reason,
    write_blocked_reason,
)
from daedalus.spine import attempt as attempt_mod   # noqa: E402


@pytest.fixture
def trees(tmp_path):
    """A stand-in primary checkout and a stand-in worktree, siblings."""
    repo = tmp_path / "checkout"
    (repo / "daedalus").mkdir(parents=True)
    (repo / "daedalus" / "sensitivity.py").write_text("# real", encoding="utf-8")
    worktree = tmp_path / "worktrees" / "candidate"
    (worktree / "daedalus").mkdir(parents=True)
    (worktree / "daedalus" / "sensitivity.py").write_text("# candidate",
                                                          encoding="utf-8")
    return repo, worktree


# --------------------------------------------------------------------------- #
# the pair the whole module exists for                                         #
# --------------------------------------------------------------------------- #
def test_the_same_write_is_refused_in_the_checkout_and_allowed_in_a_worktree(
        trees):
    """THE invariant, stated as one comparison: identical relative path, one
    tree apart, opposite verdicts."""
    repo, worktree = trees
    rel = Path("daedalus") / "sensitivity.py"

    blocked = write_blocked_reason(repo / rel, repo)
    allowed = write_blocked_reason(worktree / rel, repo)

    assert blocked is not None, "a write into the primary checkout was allowed"
    assert "inside the primary checkout" in blocked
    assert allowed is None, f"a write into the worktree was refused: {allowed}"


def test_assert_write_allowed_raises_for_the_checkout_and_returns_for_a_worktree(
        trees):
    repo, worktree = trees
    rel = Path("daedalus") / "sensitivity.py"

    with pytest.raises(PrimaryCheckoutWrite) as excinfo:
        assert_write_allowed(repo / rel, repo)
    assert "promotion" in str(excinfo.value)

    got = assert_write_allowed(worktree / rel, repo)
    assert got == (worktree / rel).resolve()


def test_a_file_that_does_not_exist_yet_is_judged_by_its_GROUND(trees):
    """The probe. A new file has no identity of its own; the fence must ask
    what it will land ON, or it refuses every creation (an outage, not a
    boundary) or allows every creation (no fence at all)."""
    repo, worktree = trees

    new_in_repo = repo / "brand" / "new" / "file.py"
    new_in_worktree = worktree / "brand" / "new" / "file.py"
    assert not new_in_repo.exists() and not new_in_worktree.exists()

    assert write_blocked_reason(new_in_repo, repo) is not None
    assert write_blocked_reason(new_in_worktree, repo) is None


def test_a_relative_path_cannot_walk_out_of_the_worktree_into_the_checkout(
        trees):
    """``..`` is resolved before comparison. A fence a path walks out of is not
    a fence -- and the paired half proves ``..`` is not simply banned."""
    repo, worktree = trees

    escaping = worktree / ".." / ".." / "checkout" / "daedalus" / "x.py"
    staying = worktree / "daedalus" / ".." / "daedalus" / "x.py"

    assert write_blocked_reason(escaping, repo) is not None
    assert write_blocked_reason(staying, repo) is None


@pytest.mark.skipif(not hasattr(os, "symlink"),
                    reason="platform has no symlink support")
def test_a_symlink_pointing_into_the_checkout_is_resolved_and_refused(trees):
    """Identity follows reparse points, so a link that LANDS on the checkout is
    exactly as refused as the checkout's own name."""
    repo, worktree = trees
    link = worktree / "shortcut"
    decoy = worktree / "ordinary"
    decoy.mkdir()
    try:
        os.symlink(repo, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation requires privilege on this box")

    assert write_blocked_reason(link / "daedalus" / "x.py", repo) is not None
    assert write_blocked_reason(decoy / "x.py", repo) is None


# --------------------------------------------------------------------------- #
# fail-closed: everything unresolvable refuses                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [None, "", "   "])
def test_input_that_cannot_be_resolved_is_refused_not_guessed_at(bad, trees):
    """``Path("").resolve()`` is the current working directory. Rewriting
    "nowhere" into "wherever the process is standing" is the helpfulness a
    fence must not offer."""
    repo, worktree = trees
    assert write_blocked_reason(bad, repo) is not None
    # paired: a real path under the same root still passes
    assert write_blocked_reason(worktree / "x.py", repo) is None


def test_a_checkout_that_cannot_be_examined_refuses_everything(tmp_path, trees):
    """If we cannot locate what we are protecting, we protect everything."""
    _repo, worktree = trees
    missing = tmp_path / "no_such_checkout"

    reason = write_blocked_reason(worktree / "x.py", missing)
    assert reason is not None
    assert "could not be examined" in reason


def test_the_default_root_is_this_repository_not_unfenced(trees):
    """A caller who forgets to name a tree gets the fence, not a bypass.

    Anchored on the fence module's OWN file rather than this test's, which is
    definitionally inside the checkout wherever the test file itself is put.
    """
    import daedalus.primary_tree as pt
    _repo, worktree = trees
    in_repo = Path(pt.__file__).resolve()

    assert write_blocked_reason(in_repo) is not None       # no repo_root given
    assert write_blocked_reason(worktree / "x.py") is None


# --------------------------------------------------------------------------- #
# alias spellings of the REAL checkout                                         #
# --------------------------------------------------------------------------- #
def _alias_spellings(root: Path) -> dict:
    """Windows names for one directory that ``Path.resolve()`` does NOT fold
    together. Measured: these compare unequal under ``resolve()`` and equal
    under ``st_dev``/``st_ino``, which is why the fence compares identity."""
    r = str(root)
    tail = os.sep + "daedalus" + os.sep + "x.py"
    out = {
        "lowercased": r.lower() + tail,
        "dotdot walk-back": os.path.join(r, "daedalus", "..", "daedalus", "x.py"),
        "dotdot escape-in": os.path.join(r, "..", root.name, "daedalus", "x.py"),
        "forward slashes": r.replace("\\", "/") + "/daedalus/x.py",
    }
    if os.name == "nt" and len(r) > 2 and r[1] == ":":
        drive, rest = r[0], r[2:]
        out["dos-device"] = "\\\\?\\" + r + tail
        out["UNC admin share"] = f"\\\\localhost\\{drive}${rest}{tail}"
        out["UNC via 127.0.0.1"] = f"\\\\127.0.0.1\\{drive}${rest}{tail}"
    return out


@pytest.mark.parametrize(
    "name", sorted(_alias_spellings(Path(attempt_mod.ROOT))))
def test_every_alias_spelling_of_the_real_checkout_is_refused(name):
    """The fence is aimed at THIS repository, under names that do not look
    like it. A text-only guard was measured letting ``git add -A`` stage files
    in the checkout through the DOS-device and UNC admin-share spellings."""
    root = Path(attempt_mod.ROOT)
    spelling = _alias_spellings(root)[name]
    if nearest_existing(Path(spelling)).exists() is False:      # pragma: no cover
        pytest.skip(f"{name} is not reachable on this box")

    assert write_blocked_reason(spelling, root) is not None, (
        f"the fence allowed a write into the primary checkout spelled {name}")


def test_the_alias_test_above_is_not_vacuous(tmp_path):
    """Paired half for the whole parametrized block: the same shapes, aimed at
    a directory that is NOT the checkout, must be allowed. Without this, the
    block passes when the fence blocks everything."""
    root = Path(attempt_mod.ROOT)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    assert write_blocked_reason(str(elsewhere).lower() + os.sep + "x.py",
                                root) is None
    assert write_blocked_reason(
        os.path.join(str(elsewhere), "a", "..", "x.py"), root) is None


# --------------------------------------------------------------------------- #
# the two questions are NOT the same question                                  #
# --------------------------------------------------------------------------- #
def test_write_and_overlap_diverge_on_the_contains_direction(trees, tmp_path):
    """Pins the deliberate split. ``overlap_reason`` refuses a directory that
    CONTAINS the checkout (``git add -A`` there stages the developer's tree);
    the write fence must not, or it fences off the whole parent directory
    without protecting anything. If these two ever agree here, somebody has
    collapsed them back into one predicate."""
    repo, _worktree = trees
    container = tmp_path                     # contains `checkout/`

    assert overlap_reason(container, repo) == "it contains the primary checkout"
    assert write_blocked_reason(container / "sibling" / "x.py", repo) is None


def test_attempt_module_uses_the_shared_comparison_not_its_own(trees):
    """The anti-duplication pin. ``spine/attempt.py`` must not regrow a private
    copy of the overlap comparison -- that is how ``eval/correctness.py`` came
    to answer the same question fail-OPEN while this one fails closed."""
    import daedalus.primary_tree as pt

    assert attempt_mod._overlap_reason is pt.overlap_reason
    assert attempt_mod._identity is pt._identity
    assert attempt_mod.PrimaryCheckoutWrite is pt.PrimaryCheckoutWrite
    assert attempt_mod._existing_ancestor is pt.nearest_existing


def test_nearest_existing_stops_at_the_first_real_directory(trees):
    repo, _worktree = trees
    assert nearest_existing(repo / "a" / "b" / "c" / "d.py") == repo
    assert nearest_existing(repo) == repo


# --------------------------------------------------------------------------- #
# the fence, reached THROUGH the product                                       #
# --------------------------------------------------------------------------- #
def _artifact():
    from daedalus.spine.attempt import PatchArtifact
    diff = b"--- a\n+++ b\n"
    return PatchArtifact(
        task_id="t", branch="b", base_revision="0" * 40,
        diff_bytes=diff, diff_sha256=hashlib.sha256(diff).hexdigest(),
        changed_paths=("a",), created_ts="1970-01-01T00:00:00+00:00")


class _FakeAttempt:
    """Just enough of TaskAttempt to exercise the real ``_persist``."""

    def __init__(self, artifact_dir, repo_root):
        self._artifact_dir = Path(artifact_dir)
        self.repo_root = Path(repo_root)

    _persist = attempt_mod.TaskAttempt._persist


def test_persist_refuses_an_artifact_dir_inside_the_checkout(trees):
    """A guard nobody has seen refuse is a guard nobody knows works. This is
    the hole as it actually existed: ``artifact_dir`` is a plain constructor
    argument, so pointing it at the checkout deposited candidate patch bytes
    there and created the directories on the way."""
    repo, worktree = trees
    inside = repo / "runs" / "patches"

    path, error = _FakeAttempt(inside, repo)._persist(_artifact())

    assert path is None, "candidate bytes were written into the primary checkout"
    assert error is not None and "refusing" in error
    # AND NOTHING WAS CREATED ON THE WAY. Refusing after mkdir would still
    # leave a mark on the checkout.
    assert not (repo / "runs").exists()


def test_persist_writes_happily_into_a_worktree(trees):
    """The paired half. The fence must not have simply broken persistence."""
    repo, worktree = trees
    outside = worktree / "runs" / "patches"

    path, error = _FakeAttempt(outside, repo)._persist(_artifact())

    assert error is None, error
    assert path is not None
    written = Path(path)
    assert written.read_bytes() == b"--- a\n+++ b\n"
    assert written.parent.name == hashlib.sha256(b"--- a\n+++ b\n").hexdigest()[:2]
    assert written.name == hashlib.sha256(b"--- a\n+++ b\n").hexdigest()[2:]
