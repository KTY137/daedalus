"""An evaluation must prove it scored the CANDIDATE, not the host.

ADR-015 Finding 1: the runner called a bare ``pytest``, ``daedalus`` resolved to
the primary checkout through the editable install's ``_EditableFinder``, and the
loop graded the host against itself. Closed 2026-07-29 by using
``sys.executable -m pytest`` with ``cwd`` in the worktree.

These tests exist because that fix is an argument about import ORDERING and
nothing checked the argument still held. Every failure mode below has the same
worst-possible shape: the tests pass, the score is high, and it describes a tree
nobody edited.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from daedalus.eval.provenance import check_import_provenance
from daedalus.eval.tasks import AGENT_ENV_ROOT


class TheRealCheckoutPasses(unittest.TestCase):
    def test_this_repo_resolves_to_itself(self):
        got = check_import_provenance(AGENT_ENV_ROOT)
        self.assertTrue(got.ok, got.reason)
        self.assertTrue(got.resolved)
        self.assertIn("daedalus", str(got.resolved))


class AWrongTreeIsCaught(unittest.TestCase):
    def test_a_directory_with_no_daedalus_fails(self):
        # The candidate's daedalus/ was destroyed, or never copied. On
        # 2026-07-30 an external write lane destroyed 3 of 5 modules while
        # reporting success on all five, so this is not hypothetical.
        candidate = Path(tempfile.mkdtemp())
        outside = Path(tempfile.mkdtemp())
        package = outside / "daedalus"
        package.mkdir()
        (package / "__init__.py").write_text(
            "ORIGIN = 'outside-candidate'\n", encoding="utf-8"
        )
        # Make the historical shadowing failure deterministic.  Depending on
        # whether this checkout is installed editable, an empty candidate alone
        # either imports the host checkout or imports nothing; this explicit
        # outside package always exercises the wrong-tree branch.
        with mock.patch.dict(os.environ, {"PYTHONPATH": str(outside)}):
            got = check_import_provenance(candidate)
        self.assertFalse(got.ok)
        self.assertIn("OUTSIDE", got.reason)

    def test_the_failure_says_EVALUATION_and_never_candidate(self):
        # A reader must not be able to mistake "could not run" for "ran badly".
        # -1.0 (unscored) and 0.0 (measured, failed) are different outcomes and
        # only one of them should influence a promotion.
        got = check_import_provenance(tempfile.mkdtemp())
        msg = got.as_error()
        self.assertIn("EVALUATION VOID", msg)
        self.assertIn("not a candidate failure", msg)


class ItFailsClosed(unittest.TestCase):
    """Every "cannot tell" is a failure, because "we could not establish which
    tree would be scored" and "the wrong tree would be scored" have the same
    consequence for a promotion decision."""

    def test_a_missing_interpreter_fails_rather_than_raising(self):
        got = check_import_provenance(AGENT_ENV_ROOT,
                                      executable="definitely-not-a-python-xyz")
        self.assertFalse(got.ok)
        self.assertIn("probe", got.reason)

    def test_a_probe_that_cannot_import_daedalus_fails(self):
        # A bare interpreter in an empty dir with no daedalus anywhere: the probe
        # runs fine and reports an import error, which is fatal for THIS
        # evaluation even though it says nothing about the repo.
        empty = tempfile.mkdtemp()
        probe = subprocess.CompletedProcess(
            args=[sys.executable, "-c", "probe"],
            returncode=0,
            stdout=(
                '{"import_error": "ModuleNotFoundError: No module named '
                "'daedalus'\"}\n"
            ),
            stderr="",
        )
        with mock.patch(
            "daedalus.eval.provenance.subprocess.run", return_value=probe
        ):
            got = check_import_provenance(empty)
        self.assertFalse(got.ok)
        self.assertIsNone(got.resolved)
        self.assertIn("ModuleNotFoundError", got.raw["import_error"])
        self.assertIn("cannot import daedalus", got.reason)
        self.assertIn("EVALUATION VOID", got.as_error())

    def test_a_zero_timeout_fails_rather_than_passing(self):
        got = check_import_provenance(AGENT_ENV_ROOT, timeout_s=0.0)
        self.assertFalse(got.ok)
        self.assertIn("probe", got.reason)


class ARealShadowingWorktreeIsAccepted(unittest.TestCase):
    """The positive case that matters: a *copy* of the package in another
    directory must be recognised as that directory's, not as the host's.

    This is the whole mechanism under test. A minimal package is enough -- the
    check asks where the name resolves, not whether the code is any good.
    """

    def test_a_shadowing_copy_resolves_to_the_candidate(self):
        root = Path(tempfile.mkdtemp())
        pkg = root / "daedalus"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("VERSION = 'candidate'\n",
                                         encoding="utf-8")
        got = check_import_provenance(root)
        self.assertTrue(got.ok, got.reason)
        self.assertTrue(str(Path(got.resolved).resolve()).startswith(
            str(root.resolve())),
            f"resolved to {got.resolved}, which is not under {root}")

    def test_a_namespace_package_with_no_init_still_resolves(self):
        # No __init__.py means __file__ is None and only __path__ answers. Without
        # checking __path__ this would read as "no answer" rather than the
        # correct "the candidate's".
        root = Path(tempfile.mkdtemp())
        (root / "daedalus").mkdir()
        (root / "daedalus" / "thing.py").write_text("x = 1\n", encoding="utf-8")
        got = check_import_provenance(root)
        self.assertTrue(got.ok, got.reason)


class TheEvolutionRunnerUsesIt(unittest.TestCase):
    def test_evaluate_candidates_voids_rather_than_scoring_zero(self):
        # Wiring test: the point of the check is the OUTCOME it produces, and a
        # check whose failure scored 0.0 would let an unrunnable evaluation argue
        # against a candidate nobody judged.
        import inspect
        from daedalus.kairos import evolution
        src = inspect.getsource(evolution.EvolutionaryOrchestrator.evaluate_candidates)
        self.assertIn("check_import_provenance", src,
                      "the runner must verify provenance, not rely on sys.path "
                      "ordering documented in a docstring")
        # The void marker, not the failure score.
        idx = src.index("check_import_provenance")
        after = src[idx:idx + 600]
        self.assertIn("-1.0", after)

    def test_the_runner_still_invokes_pytest_through_the_interpreter(self):
        # The ordering mechanism and the assertion are complementary, not
        # alternatives: bare `pytest` looks identical in a diff and is silently
        # wrong, so both are pinned.
        import inspect
        from daedalus.kairos import evolution
        src = inspect.getsource(evolution.EvolutionaryOrchestrator.evaluate_candidates)
        self.assertIn('sys.executable, "-m", "pytest"', src)


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
