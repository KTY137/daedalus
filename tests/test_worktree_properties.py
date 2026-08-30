# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Property-based invariants for daedalus.kairos.worktree (docs/ABSORPTION.md D1).

WHY THIS FILE EXISTS, AND WHY WORKTREE.PY FIRST
------------------------------------------------
``docs/FITNESS_SIGNAL.md`` F1, recorded in advance: mutation testing will be
GREEN on the pre-fix state of the `worktree.py` repository-deletion incidents,
"because you cannot mutate a guard that was never written." MEASURED
2026-07-29 (see FITNESS_SIGNAL.md's F1 section): the pre-fix commit
(``b2de339``) scored 50.0% under `tools/mutation_score.py`, and every one of
its 8 mutants was in ordinary argument plumbing -- none of them could
represent the actual defect, because the guard that would need mutating
(``_refuse_if_the_primary_checkout_moved``) did not exist yet to be found.

A property-based invariant does not have that blind spot (docs/ABSORPTION.md
I2): "no path outside the worktree root was unlinked" is checkable after
every generated operation sequence whether or not a guard exists to be
mutated. This is the "second arm" ABSORPTION.md D1 asks F1 to grow: run this
beside diff-scoped mutation on the same question and get a measured statement
about what each signal covers, rather than trusting either alone.

THE TWO INCIDENTS THIS IS MODELLED ON (docs/HANDOFF.md; the corpus entries in
tools/gate_discrimination.py):

    worktree_moved_checkout_unguarded    Round 1: the primary checkout renamed
                                          into the worktree, a junction hung on
                                          the vacated name -- 40/40 tracked
                                          files destroyed, nothing refused.
    worktree_drain_skips_reachability    Round 2: a junction renamed over an
                                          already-drained subdirectory redirects
                                          every remaining rmdir out of the tree
                                          -- 3/3, 3000 directories removed,
                                          reported as success.

Both are sequences of filesystem operations with a rename/junction in the
middle -- precisely what a ``RuleBasedStateMachine`` generates and can shrink.
This file attacks the FIRST shape directly (a live, still-open worktree
allocation is replaced with a junction aimed at the primary checkout) and
checks the invariant the module's docstring claims the CURRENT code holds:
cleanup never removes or modifies anything through a reparse point planted
where an allocated worktree used to be.

NON-NEGOTIABLE CONFIGURATION (docs/ABSORPTION.md D1's own closing paragraph),
or this file would make FITNESS_SIGNAL.md's numbers worse, not better:

    derandomize=True, a pinned seed        F4 (stability) was measured passing
                                            with ZERO status disagreements on
                                            n=10; a random-by-default generator
                                            would make F4 red by construction.

MEASURED, not assumed, correcting the plan ABSORPTION.md D1 stated: that
document also asks for an explicit, out-of-repo example DATABASE path, on the
theory that a database inside a `HeadOnlySandbox` clone would vanish with the
clone or leak host state in. Tried first, and hypothesis 6.163.0 itself
refuses it -- ``InvalidArgument: derandomize=True implies database=None, so
passing database=... too is invalid.`` The two settings are mutually
exclusive in this version, not merely discouraged, and the reason is sound
once you see it: ``derandomize`` already means "replay the same fixed,
seed-derived sequence every time, consult no history" -- there is no
persisted state left for a database to leak or lose. The STRONGER guarantee
(byte-for-byte reproducible from source alone, which is what F4 actually
needs) subsumes the weaker one, so this file passes NO ``database=`` argument
at all rather than fighting the library to keep a setting that would be
inert if it were even accepted.

WHAT THIS DOES NOT CLAIM. ``mklink /J`` needs no admin rights on Windows (the
existing deterministic suite, tests/test_worktree.py::_make_junction, already
relies on this) and this file is Windows-only for the same reason the rest of
the junction suite is -- skipped elsewhere, not faked. This does not attack
the "move the checkout wholesale INTO a worktree" shape
(``GitWorktreeManager._refuse_if_the_primary_checkout_moved``'s own docstring
calls that "A MITIGATION, NOT A CLOSURE" with a stated, admitted residual
window) -- asserting a full guarantee there would misrepresent what the code
itself claims. Real git subprocesses, real junctions, real disposable temp
directories; nothing here touches this repository's own checkout.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

try:
    from hypothesis import HealthCheck, settings
    from hypothesis.stateful import Bundle, RuleBasedStateMachine, rule, invariant
    _HYPOTHESIS_IMPORT_ERROR: Exception | None = None
except Exception as _exc:                      # pragma: no cover - see skip below
    _HYPOTHESIS_IMPORT_ERROR = _exc

from daedalus.kairos.worktree import (
    GitWorktreeManager,
    WorktreeContainmentError,
    WorktreeRemovalRace,
)

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="directory junctions are Windows-only")


def _run_git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _init_primary_repo(path: Path) -> Path:
    """A throwaway git repo standing in for "the developer's checkout",
    carrying a SENTINEL file whose survival is the invariant under test --
    same technique as tests/test_worktree.py's `_init_git_repo`, duplicated
    (not imported) so this file has no load-bearing dependency on another
    test module's internals.
    """
    path.mkdir(parents=True, exist_ok=True)
    _run_git("init", "-q", cwd=path)
    _run_git("config", "user.name", "Property Test", cwd=path)
    _run_git("config", "user.email", "property@example.com", cwd=path)
    (path / "SENTINEL.txt").write_text("the primary checkout\n", encoding="utf-8")
    (path / "src").mkdir()
    (path / "src" / "deep.txt").write_text("years of work\n", encoding="utf-8")
    _run_git("add", "-A", cwd=path)
    _run_git("commit", "-q", "-m", "seed", cwd=path)
    return path


def _make_junction(link: Path, target: Path) -> bool:
    """Create a Windows directory junction (``mklink /J``) -- no admin needed.
    The attacker's tool of choice precisely because ``os.path.islink`` does
    not see it (worktree.py's own docstring, and _is_reparse_point's)."""
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True)
    return result.returncode == 0 and os.path.exists(link)


if _HYPOTHESIS_IMPORT_ERROR is None:

    @settings(
        max_examples=20,
        stateful_step_count=10,
        deadline=None,               # real subprocesses; wall time is not the claim
        derandomize=True,            # pinned, and implies database=None -- see the
                                      # module docstring for why that is correct here
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )
    class _WorktreeJunctionMachine(RuleBasedStateMachine):
        """Legitimate GitWorktreeManager operations, interleaved with one
        adversarial rule that reproduces the Round-1 incident shape, checked
        after every step against one invariant: the primary checkout is
        untouched.
        """

        worktrees = Bundle("worktrees")

        def __init__(self) -> None:
            super().__init__()
            self._orig_worktree_root_env = os.environ.get("DAEDALUS_WORKTREE_ROOT")
            self.tmp = Path(tempfile.mkdtemp(prefix="daedalus-hyp-worktree-"))
            self.primary = _init_primary_repo(self.tmp / "primary")
            self.canary = self.primary / "SENTINEL.txt"
            self._canary_bytes = self.canary.read_bytes()
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.primary,
                                  capture_output=True, text=True, check=True)
            self.head = head.stdout.strip()
            os.environ["DAEDALUS_WORKTREE_ROOT"] = str(self.tmp / "worktrees")
            self.manager = GitWorktreeManager(self.primary)
            self._branch_counter = 0
            # Worktree paths (as str, for hashability in a Bundle) currently
            # replaced by a junction aimed at self.primary -- refused by
            # cleanup_worktree, so they are never expected to disappear.
            self._corrupted: set[str] = set()

        def teardown(self) -> None:
            if self._orig_worktree_root_env is None:
                os.environ.pop("DAEDALUS_WORKTREE_ROOT", None)
            else:
                os.environ["DAEDALUS_WORKTREE_ROOT"] = self._orig_worktree_root_env
            shutil.rmtree(self.tmp, ignore_errors=True)

        @rule(target=worktrees)
        def create(self):
            self._branch_counter += 1
            path = self.manager.create_worktree(
                self.head, f"candidate-{self._branch_counter}")
            return str(path)

        @rule(wt=worktrees)
        def cleanup(self, wt):
            path = Path(wt)
            try:
                self.manager.cleanup_worktree(path)
            except (WorktreeContainmentError, WorktreeRemovalRace, RuntimeError):
                pass   # a refusal, or a reported failure, is not a breach
            if not path.exists():
                self._corrupted.discard(wt)

        @rule(wt=worktrees)
        def attacker_replaces_worktree_with_a_junction_to_primary(self, wt):
            """The Round-1 shape: a live candidate deletes its own worktree
            directory and hangs a junction on its name, pointed at the one
            directory the manager must never delete through."""
            path = Path(wt)
            if wt in self._corrupted or not path.exists():
                return
            shutil.rmtree(path, ignore_errors=True)
            if _make_junction(path, self.primary):
                self._corrupted.add(wt)

        @invariant()
        def primary_checkout_is_never_touched(self):
            assert self.primary.is_dir(), (
                "the primary checkout directory itself is gone")
            assert not os.path.islink(self.primary), (
                "the primary checkout's own path became a symlink")
            assert self.canary.is_file(), (
                "SENTINEL.txt was deleted from the primary checkout")
            assert self.canary.read_bytes() == self._canary_bytes, (
                "SENTINEL.txt content changed -- something wrote through to "
                "the primary checkout")
            assert (self.primary / "src" / "deep.txt").is_file(), (
                "a file nested under the primary checkout was deleted")

    TestWorktreeJunctionProperty = _WorktreeJunctionMachine.TestCase


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are Windows-only")
class GuardIsLoadBearingTests(unittest.TestCase):
    """The standing instruction this crew works under: "verified by ACTUALLY
    disabling it." A property test that only ever exercises the intact code
    proves nothing about whether the invariant is checking something real --
    same reasoning as tools/gate_discrimination.py's own
    `test_disabling_the_uniqueness_guard_lets_a_duplicate_anchor_apply_silently`.

    This disables ``_is_reparse_point`` -- the ONE primitive the module's own
    docstring names as what the entire no-follow walk is built on -- and
    confirms, DETERMINISTICALLY and without Hypothesis in the loop, that the
    primary_checkout_is_never_touched invariant this file's state machine
    checks after every step would actually catch the regression. Isolated at
    ``_remove_tree_no_follow`` directly (bypassing ``GitWorktreeManager``'s
    higher, independently-redundant containment layers -- MEASURED by hand
    while building this file that at least two of them ALSO refuse this exact
    attack shape on their own, so disabling only the reparse detector and
    going through the public API would not observe a regression here at all;
    that redundancy is a property of this module, not a reason to weaken what
    this test isolates).
    """

    def test_without_reparse_detection_the_walker_deletes_through_the_junction(self):
        import daedalus.kairos.worktree as worktree_module

        original = worktree_module._is_reparse_point
        tmp = Path(tempfile.mkdtemp(prefix="daedalus-guard-check-"))
        try:
            primary = tmp / "primary"
            primary.mkdir()
            canary = primary / "SENTINEL.txt"
            canary.write_text("the primary checkout\n", encoding="utf-8")
            (primary / "src").mkdir()
            (primary / "src" / "deep.txt").write_text("years of work\n",
                                                       encoding="utf-8")

            junction = tmp / "worktrees" / "candidate-1"
            junction.parent.mkdir(parents=True)
            self.assertTrue(_make_junction(junction, primary),
                            "could not stage the attack")

            # WITH the guard intact: proven first, so the disabled run below is
            # read as a REGRESSION, not as "this was always going to happen".
            worktree_module._remove_tree_no_follow(junction)
            self.assertTrue(canary.is_file(),
                            "precondition failed: the intact guard already "
                            "did not protect the canary")

            # Restage: the intact call above correctly unlinked the (intact,
            # detected) junction rather than following it.
            self.assertFalse(junction.exists())
            self.assertTrue(_make_junction(junction, primary),
                            "could not restage the attack")

            worktree_module._is_reparse_point = lambda path: False
            worktree_module._remove_tree_no_follow(junction)

            self.assertFalse(canary.is_file(),
                             "the guard disabled: the primary checkout's "
                             "SENTINEL.txt is expected to be gone here -- if "
                             "it survived, this test stopped proving anything")
            self.assertFalse((primary / "src" / "deep.txt").is_file())
        finally:
            worktree_module._is_reparse_point = original
            shutil.rmtree(tmp, ignore_errors=True)


class HypothesisOptionalTests(unittest.TestCase):
    """Pins docs/ABSORPTION.md D1 bar 6 (replacement cost): on a box without
    the `test` extra installed, this file must degrade to knowing it is
    missing, never an ImportError that takes the rest of
    `python -m unittest discover tests` down with it. Always runs (unlike the
    property class above, which only exists when hypothesis does), so this is
    the one assertion in this file that is meaningful on EVERY box.
    """

    def test_a_missing_hypothesis_is_recorded_not_raised(self):
        if _HYPOTHESIS_IMPORT_ERROR is not None:
            self.assertIsInstance(_HYPOTHESIS_IMPORT_ERROR, Exception)
        # Either way, importing this module (which already happened to reach
        # this line) must not have raised -- the meaningful assertion is that
        # test collection got this far at all.


if __name__ == "__main__":
    unittest.main()
