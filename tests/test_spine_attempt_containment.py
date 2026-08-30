# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Containment regressions for daedalus.spine.attempt's git choke point.

Kept separate from tests/test_spine_attempt.py so the guard's geometry can be
attacked directly. The claim under test is the one the module docstring makes:
a mutating git verb can never run against the primary checkout. The defect these
tests pin is DIRECTIONAL -- the guard used to ask only "is the working directory
inside the repo?", which is False for a directory that CONTAINS the repo.
"""
import os
import subprocess

import pytest

import daedalus.spine.attempt as attempt_mod
from daedalus.spine.attempt import GitCommandError, PrimaryCheckoutWrite

# Windows spellings that name the SAME directory as a plain drive-letter path.
# Measured: ``Path.resolve()`` canonicalises none of the first four into the
# drive-letter form, and before the identity check every one of them was
# ALLOWED -- ``git add -A`` ran in the primary checkout and staged files.
ALIAS_SPELLINGS = {
    "dos_device":         lambda p: f"\\\\?\\{p}",
    "dos_device_unc":     lambda p: f"\\\\?\\UNC\\localhost\\{str(p)[0]}$\\{str(p)[3:]}",
    "unc_admin_share":    lambda p: f"\\\\localhost\\{str(p)[0]}$\\{str(p)[3:]}",
    "unc_admin_share_ip": lambda p: f"\\\\127.0.0.1\\{str(p)[0]}$\\{str(p)[3:]}",
    "dos_device_dot":     lambda p: f"\\\\.\\{p}",
}


def _alias_or_skip(name, path):
    alias = ALIAS_SPELLINGS[name](path)
    if not os.path.isdir(alias):
        pytest.skip(f"{name} spelling is not reachable on this machine")
    return alias


def _staged(path):
    return subprocess.run(['git', 'diff', '--cached', '--name-only'], cwd=str(path),
                          capture_output=True, text=True, check=True).stdout.strip()


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)

    def run_git(*args):
        subprocess.run(['git', *args], cwd=path, check=True, capture_output=True)

    run_git('init')
    run_git('config', 'user.name', 'Test User')
    run_git('config', 'user.email', 'test@example.com')
    (path / "tracked.txt").write_text("original\n")
    run_git('add', '-A')
    run_git('commit', '-m', 'seed')
    return path


@pytest.fixture
def nested(tmp_path):
    """An outer repo with the "primary checkout" nested inside it.

    This is not exotic -- a workspace repo, a vendored clone, or a monorepo
    subtree all produce it, and it is the shape that turns the directional hole
    into an actual write.
    """
    outer = _init_repo(tmp_path / "outer")
    inner = _init_repo(outer / "inner")
    return outer, inner


def test_mutating_git_is_refused_in_a_directory_that_contains_the_checkout(nested):
    outer, inner = nested
    (outer / "untracked_secret.txt").write_text("must not be staged\n")

    with pytest.raises(PrimaryCheckoutWrite) as excinfo:
        attempt_mod._git(["add", "-A"], cwd=outer, repo_root=inner)

    assert "overlaps the primary checkout" in str(excinfo.value)
    # Nothing was staged in the enclosing repo.
    staged = subprocess.run(['git', 'diff', '--cached', '--name-only'], cwd=outer,
                            capture_output=True, text=True, check=True).stdout
    assert staged.strip() == ""


def test_mutating_git_is_refused_in_the_checkout_itself(nested):
    _outer, inner = nested

    with pytest.raises(PrimaryCheckoutWrite):
        attempt_mod._git(["add", "-A"], cwd=inner, repo_root=inner)


def test_mutating_git_is_refused_below_the_checkout(nested):
    _outer, inner = nested
    below = inner / "sub"
    below.mkdir()

    with pytest.raises(PrimaryCheckoutWrite):
        attempt_mod._git(["commit", "-m", "no"], cwd=below, repo_root=inner)


def test_reads_are_still_allowed_against_the_checkout(nested):
    _outer, inner = nested

    proc = attempt_mod._git(["rev-parse", "HEAD"], cwd=inner, repo_root=inner)

    assert proc.returncode == 0
    assert proc.stdout.strip()


def test_mutating_git_is_still_allowed_in_a_non_overlapping_directory(tmp_path, nested):
    """The allow case: the guard must not become "no writes anywhere"."""
    _outer, inner = nested
    sibling = _init_repo(tmp_path / "sibling")
    (sibling / "candidate.txt").write_text("candidate work\n")

    proc = attempt_mod._git(["add", "-A"], cwd=sibling, repo_root=inner)

    assert proc.returncode == 0
    staged = subprocess.run(['git', 'diff', '--cached', '--name-only'], cwd=sibling,
                            capture_output=True, text=True, check=True).stdout
    assert "candidate.txt" in staged


def test_the_guard_fires_before_the_subprocess(nested, monkeypatch):
    """A refusal must not depend on git's own opinion of the directory."""
    _outer, inner = nested

    def explode(*args, **kwargs):
        raise AssertionError("subprocess must never be reached")

    monkeypatch.setattr(attempt_mod.subprocess, "run", explode)

    with pytest.raises(PrimaryCheckoutWrite):
        attempt_mod._git(["add", "-A"], cwd=inner.parent, repo_root=inner)


def test_a_missing_verb_is_still_rejected_loudly(nested):
    _outer, inner = nested
    with pytest.raises(ValueError):
        attempt_mod._git([], cwd=inner, repo_root=inner)
    with pytest.raises(ValueError):
        attempt_mod._git(["--version"], cwd=inner, repo_root=inner)


# --------------------------------------------------------------------------- #
# ALIAS SPELLINGS. The both-directions geometry above is correct but was        #
# expressed over Path.resolve(), and realpath does not canonicalise DOS-device  #
# or UNC admin-share names. The guard therefore compared two different strings  #
# for one directory and allowed the write. Identity (st_dev/st_ino) is the      #
# comparison that holds, because it stops comparing names at all.               #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(os.name != 'nt', reason="Windows path aliases")
@pytest.mark.parametrize("alias_name", sorted(ALIAS_SPELLINGS))
def test_mutating_git_is_refused_through_a_windows_alias_of_the_checkout(
        nested, alias_name):
    _outer, inner = nested
    (inner / "untracked_secret.txt").write_text("must not be staged\n")
    alias = _alias_or_skip(alias_name, inner)

    with pytest.raises(PrimaryCheckoutWrite):
        attempt_mod._git(["add", "-A"], cwd=alias, repo_root=inner)

    assert _staged(inner) == ""


@pytest.mark.skipif(os.name != 'nt', reason="Windows path aliases")
@pytest.mark.parametrize("alias_name", sorted(ALIAS_SPELLINGS))
def test_mutating_git_is_refused_in_a_subdirectory_named_through_an_alias(
        nested, alias_name):
    """Inside-the-checkout, one alias down: the ancestor walk has to see it too."""
    _outer, inner = nested
    (inner / "untracked_secret.txt").write_text("must not be staged\n")
    (inner / "sub").mkdir(exist_ok=True)
    alias = _alias_or_skip(alias_name, inner / "sub")

    with pytest.raises(PrimaryCheckoutWrite):
        attempt_mod._git(["add", "-A"], cwd=alias, repo_root=inner)

    assert _staged(inner) == ""


@pytest.mark.skipif(os.name != 'nt', reason="Windows path aliases")
@pytest.mark.parametrize("alias_name", sorted(ALIAS_SPELLINGS))
def test_an_alias_of_an_unrelated_repo_is_not_refused(tmp_path, nested,
                                                      alias_name):
    """The allow case for the identity check: it must not become "no writes".

    Git's own opinion of an odd spelling is not this guard's business, so a
    GitCommandError is an acceptable outcome here; a PrimaryCheckoutWrite is
    not, because that would mean the guard over-refused.
    """
    _outer, inner = nested
    sibling = _init_repo(tmp_path / "unrelated")
    (sibling / "candidate.txt").write_text("candidate work\n")
    alias = _alias_or_skip(alias_name, sibling)

    try:
        attempt_mod._git(["add", "-A"], cwd=alias, repo_root=inner)
    except PrimaryCheckoutWrite as e:
        pytest.fail(f"the guard over-refused an unrelated directory: {e}")
    except GitCommandError:
        pass


def test_mutating_git_is_refused_when_the_directory_cannot_be_examined(
        nested, tmp_path):
    """Fail closed. A path we cannot stat is not assumed innocent.

    Deliberately OUTSIDE the checkout textually, so the text comparison says
    "no overlap" and only the unexaminable-means-refused rule can fire.
    """
    _outer, inner = nested
    vanished = tmp_path / "vanished"

    with pytest.raises(PrimaryCheckoutWrite) as excinfo:
        attempt_mod._git(["add", "-A"], cwd=vanished, repo_root=inner)

    assert "could not be examined" in str(excinfo.value)


def test_mutating_git_is_refused_when_the_checkout_cannot_be_examined(
        tmp_path, nested):
    """If we cannot locate what we are protecting, we protect everything."""
    _outer, inner = nested
    sibling = _init_repo(tmp_path / "unrelated_sibling")

    with pytest.raises(PrimaryCheckoutWrite) as excinfo:
        attempt_mod._git(["add", "-A"], cwd=sibling,
                         repo_root=tmp_path / "no_such_checkout")

    assert "could not be examined" in str(excinfo.value)


def test_git_failures_outside_the_checkout_are_still_reported(tmp_path, nested):
    """Unrelated failures stay GitCommandError, not silently swallowed."""
    _outer, inner = nested
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()

    with pytest.raises(GitCommandError):
        attempt_mod._git(["add", "-A"], cwd=not_a_repo, repo_root=inner)


# --------------------------------------------------------------------------- #
# THE GATE'S SCRATCH DIRECTORY. `pytest_gate` is the DEFAULT gate; it creates   #
# %TEMP%/daedalus-gate-* and runs pytest INSIDE the candidate worktree, i.e. it #
# executes candidate-written code. That scratch directory used to be removed by #
# `shutil.rmtree(tmpdir, ignore_errors=True)` in a `finally:` -- an unguarded   #
# recursive delete whose failures were, by construction, invisible.             #
#                                                                               #
# Measured on this box (CPython 3.10.11): shutil.rmtree is safe against a       #
# junction that is ALREADY in place, and unsafe against one renamed in mid-walk #
# (its check reads the Windows scandir stat cache) -- victim destroyed 3/3 with #
# the victim in the last entry position. Containment of the CHILD rests on the  #
# ManagedProcess Job Object; containment of the FILESYSTEM rests on nothing but #
# this delete, which is why it is routed through the guarded walker.            #
# --------------------------------------------------------------------------- #
def _make_junction(link, target):
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                            capture_output=True)
    return result.returncode == 0 and os.path.exists(link)


def test_gate_scratch_removal_does_not_follow_a_junction_planted_in_it(tmp_path):
    """The allow case and the block case in one: scratch gone, target intact.

    Honest note: ``shutil.rmtree(ignore_errors=True)`` also passes this on
    CPython 3.10.11 -- an in-place junction is one of the cases it gets right.
    This is a regression pin, not the mutation-killing test; that is the next
    two.
    """
    tmpdir = tmp_path / "daedalus-gate-abc"
    tmpdir.mkdir()
    (tmpdir / "gate.out").write_text("captured output")
    victim = _init_repo(tmp_path / "primary_checkout")
    assert _make_junction(tmpdir / "trap", victim), "could not stage the attack"

    assert attempt_mod._remove_gate_tmpdir(tmpdir) is None
    assert not tmpdir.exists()
    assert (victim / "tracked.txt").read_text() == "original\n"
    assert (victim / ".git").exists()


def test_gate_scratch_removal_is_routed_through_the_guarded_walker(tmp_path,
                                                                   monkeypatch):
    """Two claims at once, and both die if the ``shutil`` call comes back.

    1. the delete goes through ``_remove_tree_no_follow`` -- the spy only fires
       if it does;
    2. a delete that could NOT be completed is REPORTED. ``ignore_errors=True``
       is a silent delete failure in a ``finally:``, which is the exact shape
       this codebase refuses everywhere else it deletes.
    """
    import daedalus.kairos.worktree as worktree_module

    tmpdir = tmp_path / "daedalus-gate-def"
    tmpdir.mkdir()
    (tmpdir / "gate.out").write_text("captured output")
    calls = []

    def refusing_remove(path, guarded_ancestors=()):
        calls.append(str(path))
        raise OSError("permission denied")

    monkeypatch.setattr(worktree_module, '_remove_tree_no_follow', refusing_remove)

    report = attempt_mod._remove_gate_tmpdir(tmpdir)

    assert calls == [str(tmpdir)], "the guarded walker was not the thing that ran"
    assert report and "was NOT removed" in report
    assert str(tmpdir) in report
    assert "permission denied" in report


def test_the_gate_reports_a_scratch_directory_it_could_not_remove(tmp_path,
                                                                 monkeypatch):
    """The WIRING: the gate's ``finally:`` must call it AND surface the report.

    A guard the real path never invokes is decoration, so this runs the default
    gate end to end (a real pytest subprocess in a real worktree-shaped
    directory) rather than calling the helper.
    """
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "test_trivial.py").write_text("def test_ok():\n    assert True\n")

    seen = []

    def failing_cleanup(path):
        seen.append(path)
        return "[gate scratch directory SENTINEL was NOT removed: OSError: nope]"

    monkeypatch.setattr(attempt_mod, '_remove_gate_tmpdir', failing_cleanup)

    task = attempt_mod.TaskSpec(task_id="t", instruction="i",
                                gate_paths=("test_trivial.py",))
    ctx = attempt_mod.RunnerContext(worktree=worktree, branch="b",
                                    base_revision="HEAD", task=task,
                                    is_cancelled=lambda: False)
    result = attempt_mod.pytest_gate(task.gate_paths, timeout_s=120)(ctx)

    assert seen, "the gate's finally: never removed its scratch directory"
    assert "SENTINEL was NOT removed" in result.output, (
        "a scratch directory the gate could not remove vanished from the report")
    # The verdict is about the CANDIDATE, never about our own housekeeping.
    assert result.passed is True
