"""The planning half of ``python.offload`` cannot write. That is the guard.

THE DEFECT THIS CLOSES, measured at merge 21f21f2a. ``python.offload`` was the
one registry row that authenticated an Effect Lease with zero refusals, and it
dominated no blocking write surface at all: its only write --
``worker.run(**run_kwargs)`` -- sat in ``_offload_impl``, which the un-leased
``live=False`` planning path also called, and which four test modules imported
and called directly with ``live=True``. A write reachable from a leased caller
AND from an un-leased one is attributable to neither, so
``scripts/declare_write_surfaces.py`` refused to count it and the report line
read "authenticated, and its anchor dominates no blocking write surface".

THE SHAPE NOW. ``_offload_impl`` routes, refuses, and returns a DESCRIPTION of
the dispatch. It never runs a provider. The executor is a module-private helper
named exactly once in ``daedalus/offload.py``, from the statement in
:func:`offload` that follows ``effect_authorization.begin_effect(...)``. These
tests pin the behavioural half of that claim; the declaration half is pinned by
``tests/gates/test_write_surface_lease_dominance.py``.

Deliberately NOT spelled anywhere below: the executor's name. The declaration's
private-callee fixpoint admits a helper only when its name appears in NO other
Python source in the tree, so naming it here would silently un-declare the very
surface these tests exist to protect. The tests reach it the only way anything
should -- through the public entrypoint, behind a real lease.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus import metrics
from daedalus.offload import _LIVE_DISPATCH_KEY, _offload_impl, offload

from test_offload_lease_harness import live_offload

_OBJECTIVE = "improve the helper defaults"
_TARGET = "docs/notes_helper.py"
_ORIGINAL = "def blurb():\n    return 'hi'\n"
_AVAIL = {"claude_cli": True, "ollama": True, "deepseek": False, "codex_cli": False}

_REPORT = {"status": "done", "summary": "s", "files_changed": [],
           "tests_run": [], "risks": [], "todos": [], "handoff": {}}


def _repo(tmp: str) -> str:
    """The same hermetic fixture the write-lane tests use: one benign docs
    module, a loaded policy (writes are refused without one) and a repo-local
    agent, so routing never consults the developer's machine."""

    root = Path(tmp)
    target = root / _TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_ORIGINAL, encoding="utf-8")
    cfg = root / ".agentenv"
    (cfg / "agents").mkdir(parents=True, exist_ok=True)
    (cfg / "agentenv.json").write_text(
        '{"policy": {"default_deny": true, "allow": ["docs/"]}}', encoding="utf-8")
    (cfg / "agents" / "helper-dev.json").write_text(
        '{"name": "helper-dev", "call_name": "Help", "model_tier": "sonnet",'
        ' "external_ok": true, "owns": ["docs"], "triggers": ["helper", "improve"],'
        ' "must_read": [], "output_schema": "agent_report_v1",'
        ' "category": "implementation"}', encoding="utf-8")
    return str(root)


class _Worker:
    """Writes the declared target when it is run at all, and records that it
    was. A worker that is never reached leaves ``runs == 0`` and the file
    untouched -- which is the assertion in every negative test below."""

    def __init__(self, repo_root: str) -> None:
        self._root = repo_root
        self.runs = 0
        self._backup: bytes | None = None
        self.rollback_failures: list[str] = []

    def run(self, **kwargs):
        self.runs += 1
        path = Path(self._root) / _TARGET
        self._backup = path.read_bytes() if path.exists() else None
        path.write_text("def blurb():\n    return 'bye'\n", encoding="utf-8")
        return {"report": dict(_REPORT)}

    def rollback(self):
        path = Path(self._root) / _TARGET
        if self._backup is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(self._backup)
        return [_TARGET]


class UnleasedPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_log = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"
        self.repo = _repo(self._tmp.name)
        self.worker = _Worker(self.repo)

    def tearDown(self) -> None:
        metrics.LOG = self._orig_log
        self._tmp.cleanup()

    def _body(self) -> str:
        return (Path(self.repo) / _TARGET).read_text(encoding="utf-8")

    # ------------------------------------------------------------------ #
    # the un-leased callers                                              #
    # ------------------------------------------------------------------ #
    def test_the_planner_called_directly_and_live_runs_no_provider(self):
        """THE CASE THAT USED TO WRITE. Importing ``_offload_impl`` and calling
        it with ``live=True`` was a complete, un-leased write path. It now
        returns a plan: the provider seam is never reached and the file on disk
        is byte-identical."""

        with mock.patch("daedalus.providers.get_provider",
                        return_value=self.worker) as provider:
            result = _offload_impl(
                _OBJECTIVE, self.repo, [_TARGET], True, _AVAIL,
                _attempt_workspace={"worktree": self.repo})

        provider.assert_not_called()
        self.assertEqual(self.worker.runs, 0)
        self.assertEqual(self._body(), _ORIGINAL)
        # It returned a description of the dispatch, not the result of one.
        self.assertIn(_LIVE_DISPATCH_KEY, result)
        self.assertNotIn("action", result)
        self.assertNotIn("verify", result)

    def test_the_plan_it_hands_back_carries_no_way_to_run_itself(self):
        """Holding the plan is not holding the writer. The dispatch is data:
        it names no provider object and exposes no callable attribute, so an
        un-leased caller that obtains one still has to find the executor -- and
        the executor is named in exactly one leased statement."""

        with mock.patch("daedalus.providers.get_provider",
                        return_value=self.worker):
            result = _offload_impl(
                _OBJECTIVE, self.repo, [_TARGET], True, _AVAIL,
                _attempt_workspace={"worktree": self.repo})

        dispatch = result[_LIVE_DISPATCH_KEY]
        callables = [
            name
            for name in vars(dispatch)
            if callable(getattr(dispatch, name, None))
        ]
        self.assertEqual(callables, [])
        self.assertEqual(self.worker.runs, 0)

    def test_planning_mode_never_builds_a_dispatch_at_all(self):
        """``live=False`` is a read-only planning operation, and it does not
        even produce the plan object -- it terminates at ``would_offload``."""

        with mock.patch("daedalus.providers.get_provider",
                        return_value=self.worker) as provider:
            result = offload(_OBJECTIVE, self.repo, [_TARGET], live=False,
                             availability=_AVAIL)

        provider.assert_not_called()
        self.assertEqual(result["action"], "would_offload")
        self.assertNotIn(_LIVE_DISPATCH_KEY, result)
        self.assertEqual(self._body(), _ORIGINAL)

    def test_a_live_call_without_a_lease_never_reaches_the_planner(self):
        """The refusal is still ahead of everything: no provider, no write."""

        with mock.patch("daedalus.providers.get_provider",
                        return_value=self.worker) as provider:
            result = offload(_OBJECTIVE, self.repo, [_TARGET], live=True,
                             availability=_AVAIL,
                             _attempt_workspace={"worktree": self.repo})

        provider.assert_not_called()
        self.assertEqual(result["action"], "effect_lease_required")
        self.assertEqual(result["wrote"], [])
        self.assertEqual(self._body(), _ORIGINAL)

    # ------------------------------------------------------------------ #
    # the positive control                                               #
    # ------------------------------------------------------------------ #
    def test_the_leased_call_does_reach_the_write(self):
        """Without this the tests above prove nothing: a path that never writes
        under any circumstances is not a guard, it is a dead seam."""

        with mock.patch("daedalus.providers.get_provider",
                        return_value=self.worker):
            result = live_offload(_OBJECTIVE, self.repo, paths=[_TARGET],
                                  availability=_AVAIL)

        self.assertEqual(result["action"], "offloaded", result)
        self.assertEqual(self.worker.runs, 1)
        self.assertEqual(result["wrote"], [_TARGET])
        self.assertNotEqual(self._body(), _ORIGINAL)
        # And the plan key never rides out on the result an operator reads.
        self.assertNotIn(_LIVE_DISPATCH_KEY, result)


if __name__ == "__main__":
    unittest.main()
