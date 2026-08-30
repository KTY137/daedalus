# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The worktree manager's three mutating doors start centrally.

MIGRATED 2026-08-25. Before this, ``tools/effect_boundary_check.py`` reported
``gate0.not_central`` for ``worktree.create``, ``worktree.commit`` and
``worktree.cleanup``: the three calls that create a git worktree, stage and
commit inside it, and delete it again ran behind local guards only, while
``worktree.reap`` -- the one door that deletes nothing but a ref -- was already
central. The GAP count moved 19 -> 16.

These tests pin two separate claims, because the registry alone can lie in
either direction:

1. the REGISTRY says central, and keeps BOTH anchors (the local containment
   check and the central start), so deleting the local proof still fails the
   structural conformance scan;
2. the CODE really starts the effect, and starts it BEFORE the mutation --
   including the case where the mutation then fails, and the case where
   containment refuses and therefore nothing is started at all.

Claim 2 is what a static anchor cannot see: an anchor is satisfied by a
``begin_effect`` call anywhere in the function, including after the damage.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daedalus.spine.effect_boundary as boundary          # noqa: E402
from daedalus.kairos.worktree import (                     # noqa: E402
    GitWorktreeManager,
    WorktreeContainmentError,
)
from daedalus.spine.effect_boundary import (               # noqa: E402
    REGISTRY_BY_ID,
    Effect,
    Wiring,
)

MIGRATED = ("worktree.create", "worktree.commit", "worktree.cleanup")


@pytest.fixture
def worktree_root(tmp_path, monkeypatch):
    root = tmp_path / "wt_root"
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(root))
    return root


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo_path, check=True,
                       capture_output=True)

    git("init")
    git("config", "user.name", "Test User")
    git("config", "user.email", "test@example.invalid")
    (repo_path / "test.txt").write_text("initial", encoding="utf-8")
    git("add", "test.txt")
    git("commit", "-m", "Initial commit")
    return repo_path


@pytest.fixture
def starts(monkeypatch):
    """Record every central start, in order, without disabling one.

    The real ``begin_effect`` still runs and still refuses: the recorder wraps
    it rather than replacing it, so a test that passes here is not a test that
    passed because the boundary was switched off. The manager imports the name
    at call time (``_effect_boundary``), so patching the module attribute is
    what the migrated code actually resolves.
    """
    seen: list[tuple[str, tuple, tuple]] = []
    real = boundary.begin_effect

    def recording(entrypoint_id, effects, decisions, **kwargs):
        decisions = tuple(decisions)
        receipt = real(entrypoint_id, effects, decisions, **kwargs)
        seen.append((entrypoint_id, tuple(effects), decisions))
        return receipt

    monkeypatch.setattr(boundary, "begin_effect", recording)
    return seen


# -- 1. the registry ---------------------------------------------------- #

@pytest.mark.parametrize("row_id", MIGRATED)
def test_row_is_central(row_id):
    assert REGISTRY_BY_ID[row_id].wiring is Wiring.CENTRAL


@pytest.mark.parametrize("row_id", MIGRATED)
def test_row_keeps_both_anchors(row_id):
    """The central start does not replace the local containment proof.

    An anchor is the mechanical check that a named call is still in the named
    function. Swapping the local anchor for ``begin_effect`` would leave the
    receipt claiming a containment decision no code is required to make.
    """
    spec = REGISTRY_BY_ID[row_id]
    calls = {anchor.call for anchor in spec.anchors}
    assert "begin_effect" in calls
    assert calls - {"begin_effect"}, (
        f"{row_id} kept no local guard anchor; the containment check it "
        f"quotes could be deleted without any scan noticing"
    )
    assert {anchor.target for anchor in spec.anchors} == {spec.target}


@pytest.mark.parametrize("row_id", MIGRATED)
def test_row_declares_repository_mutation(row_id):
    """These three exist because they mutate a repository, not a directory."""
    assert Effect.REPOSITORY_MUTATION in REGISTRY_BY_ID[row_id].effects


# -- 2. the code -------------------------------------------------------- #

def test_create_starts_before_the_worktree_exists(repo, worktree_root, starts):
    manager = GitWorktreeManager(repo)
    path = manager.create_worktree("HEAD", "wt-a")

    assert [row for row, _, _ in starts] == ["worktree.create"]
    assert path.exists()
    _, effects, decisions = starts[0]
    assert set(effects) == set(REGISTRY_BY_ID["worktree.create"].effects)
    (decision,) = decisions
    assert decision.contract == "containment.worktree"
    assert decision.allowed
    # The evidence names the checks that ran, not the conclusion they reached.
    assert str(path) in decision.evidence
    assert "repo-adjacent" in decision.evidence


def test_commit_and_cleanup_each_start_once(repo, worktree_root, starts):
    manager = GitWorktreeManager(repo)
    path = manager.create_worktree("HEAD", "wt-b")
    (path / "new.txt").write_text("candidate work", encoding="utf-8")
    manager.commit_candidate(path, "candidate commit")
    manager.cleanup_worktree(path)

    assert [row for row, _, _ in starts] == [
        "worktree.create", "worktree.commit", "worktree.cleanup",
    ]
    assert not path.exists()


def test_refused_placement_starts_no_effect(repo, worktree_root, starts):
    """Containment refuses -> no receipt exists for an effect nothing began.

    A start recorded before the containment check would make every refused
    allocation look, in the ledger, like an authorised one that happened to
    fail.
    """
    manager = GitWorktreeManager(repo)
    with pytest.raises(WorktreeContainmentError):
        manager.create_worktree("HEAD", "../escape")
    assert starts == []


def test_cleanup_of_an_unallocated_path_starts_no_effect(
    repo, worktree_root, starts,
):
    manager = GitWorktreeManager(repo)
    stranger = worktree_root / "not-ours"
    stranger.mkdir(parents=True)
    with pytest.raises(WorktreeContainmentError):
        manager.cleanup_worktree(stranger)
    assert starts == []
    assert stranger.exists(), "a refused cleanup removed the directory anyway"


def test_start_precedes_a_failing_creation(repo, worktree_root, starts,
                                           monkeypatch):
    """The receipt exists even when the mutation then dies.

    This is the ordering claim a static anchor cannot make: `git worktree add`
    is forced to fail, and the start must already have happened, because a
    partial create leaves a ref and a half-filled directory behind.
    """
    manager = GitWorktreeManager(repo)
    real_run_git = manager._run_git

    def failing(*args, **kwargs):
        if args[:1] == ("worktree",):
            raise RuntimeError("git worktree add died halfway")
        return real_run_git(*args, **kwargs)

    monkeypatch.setattr(manager, "_run_git", failing)
    with pytest.raises(RuntimeError):
        manager.create_worktree("HEAD", "wt-c")

    assert [row for row, _, _ in starts] == ["worktree.create"]
