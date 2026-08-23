"""The build vocabulary is bound to the canonical chain, not parallel to it.

Master plan §7 fixes one chain -- ``MissionContract -> WorkItems -> Attempts ->
Artifacts -> EvidencePacket`` -- while ``daedalus/build.py`` carries
``BuildSession`` / ``Wave`` / ``BuildTask``. Invariant 1 allows the second set
of nouns to survive as an internal module (plan §3) only while it is a VIEW of
the canonical one. These tests are what makes that a claim with teeth:

  * the WorkItem layer is real and deterministic (ids derive from the plan);
  * the ids are unique, including for byte-identical planned work;
  * a mission compiled from a session names exactly that session's work items;
  * an ``AttemptContract`` produced during the build names the SAME mission;
  * a wave receipt row names the mission it belongs to (Invariant 7);
  * ``build.py`` defines no second mission/attempt/evidence noun.

The last one is the structural guard. Everything else could pass while
``build.py`` quietly grew a ``MissionLedger`` beside the kernel's, which is the
Invariant-1 failure this whole item exists to prevent.

Offline: no model, no network, no repo. Run with:

    python -m unittest tests.test_build_vocabulary -v
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from daedalus.build import (
    BuildSession,
    BuildTask,
    Wave,
    mission_id_for_session,
)
from daedalus.schemas import (
    AttemptContract,
    ContractProvenance,
    ResourceBudget,
    derive_work_item_id,
)
from daedalus.spine.receipts import mission_contract_for_build_session

BUILD_PY = Path(__file__).resolve().parents[1] / "daedalus" / "build.py"

_ZERO_REVISION = "0" * 40
_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64
_CREATED_AT = "2026-08-22T00:00:00+00:00"


def _task(objective: str, *, agent: str = "core-dev", paths=("mod.py",)) -> BuildTask:
    return BuildTask(
        objective=objective,
        agent=agent,
        category="implementation",
        lane="auto",
        tier="sonnet",
        builder="claude",
        frontier=True,
        paths=list(paths),
    )


def _session(*objectives: str, slug: str = "cfg-parser",
             created: str = "20260822T000000Z",
             mission_id: str = "",
             per_wave: int = 2) -> BuildSession:
    """A session with the given objectives, chunked ``per_wave`` at a time."""
    tasks = [_task(o) for o in objectives]
    waves = [
        Wave(index=i // per_wave, tasks=tasks[i:i + per_wave])
        for i in range(0, len(tasks), per_wave)
    ]
    return BuildSession(
        feature="Add a config parser",
        repo_root="/repo",
        project=None,
        waves=waves,
        slug=slug,
        created=created,
        max_workers=per_wave,
        mission_id=mission_id,
    )


class WorkItemIdentity(unittest.TestCase):
    """BuildTask <-> WorkItem: deterministic, unique, plan-bound."""

    def test_a_session_binds_one_mission_and_one_work_item_per_task(self):
        session = _session("alpha", "beta", "gamma")
        self.assertEqual(session.mission_id,
                         mission_id_for_session("cfg-parser", "20260822T000000Z"))
        for task in session.tasks():
            self.assertEqual(task.mission_id, session.mission_id)
            self.assertTrue(task.work_item_id, "every task must carry a work item id")

    def test_work_item_ids_are_deterministic(self):
        first = _session("alpha", "beta", "gamma")
        second = _session("alpha", "beta", "gamma")
        self.assertEqual(first.work_item_ids(), second.work_item_ids())

    def test_work_item_ids_are_unique_even_for_identical_work(self):
        """Two tasks planned with byte-identical substance are still two items.

        The ordinal is what carries that, and it matters: ``work_item_ids``
        rejects duplicates, so a content-only derivation would have made a
        legitimate plan uncompilable into a mission.
        """
        session = _session("same", "same", "same")
        ids = session.work_item_ids()
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(set(ids)), 3)

    def test_the_id_is_bound_to_the_planned_substance(self):
        """Change the objective, get a different id -- the receipt proves what
        was worked, not merely where it sat in the list."""
        original = _session("alpha", "beta").work_item_ids()
        edited = _session("alpha", "beta EDITED").work_item_ids()
        self.assertEqual(original[0], edited[0])
        self.assertNotEqual(original[1], edited[1])

    def test_binding_is_idempotent(self):
        """A re-bind never renumbers settled work (a reloaded snapshot must
        keep the ids it was persisted with)."""
        session = _session("alpha", "beta")
        before = session.work_item_ids()
        session.bind_work_items()
        session.bind_work_items()
        self.assertEqual(session.work_item_ids(), before)

    def test_a_snapshot_round_trips_the_binding(self):
        session = _session("alpha", "beta")
        reloaded = BuildSession.from_dict(session.to_dict())
        self.assertEqual(reloaded.mission_id, session.mission_id)
        self.assertEqual(reloaded.work_item_ids(), session.work_item_ids())

    def test_an_explicit_mission_id_wins(self):
        """The caller that already owns a run identity (the loop's run_id)
        supplies it, so the wave lease and the session name ONE mission."""
        session = _session("alpha", mission_id="loop-20260822T0000Z-ab12")
        self.assertEqual(session.mission_id, "loop-20260822T0000Z-ab12")
        self.assertEqual(session.tasks()[0].mission_id, "loop-20260822T0000Z-ab12")

    def test_the_derivation_refuses_a_malformed_mission_id(self):
        with self.assertRaises(ValueError):
            derive_work_item_id("not a valid id", ordinal=0, identity=("x",))

    def test_the_derivation_refuses_a_bare_string_identity(self):
        with self.assertRaises(ValueError):
            derive_work_item_id("mission-x", ordinal=0, identity="alpha")


class MissionFromSession(unittest.TestCase):
    """BuildSession <-> one MissionContract run."""

    def _mission(self, session: BuildSession):
        return mission_contract_for_build_session(
            session,
            source_revision=_ZERO_REVISION,
            created_at=_CREATED_AT,
            budget=ResourceBudget(max_wall_time_s=600),
        )

    def test_the_mission_names_exactly_the_sessions_work_items(self):
        session = _session("alpha", "beta", "gamma")
        mission = self._mission(session)
        self.assertEqual(mission.mission_id, session.mission_id)
        # The contract's tuple is sorted by construction; the session's is in
        # plan order. Same SET, and order lives on the wave, never the mission.
        self.assertEqual(set(mission.work_item_ids), set(session.work_item_ids()))
        self.assertEqual(mission.objective, session.feature)

    def test_an_unbound_session_is_refused_not_papered_over(self):
        session = _session("alpha")
        session.mission_id = ""
        with self.assertRaises(ValueError):
            self._mission(session)

    def test_a_task_with_no_work_item_id_is_refused(self):
        session = _session("alpha", "beta")
        session.tasks()[1].work_item_id = ""
        with self.assertRaises(ValueError):
            self._mission(session)

    def test_duplicate_work_items_surface_instead_of_being_deduplicated(self):
        """Two tasks claiming one work item is a planning defect. The mission
        must refuse it, not silently collapse the two into one."""
        session = _session("alpha", "beta")
        session.tasks()[1].work_item_id = session.tasks()[0].work_item_id
        with self.assertRaises(ValueError):
            self._mission(session)


class AttemptCarriesTheMission(unittest.TestCase):
    """A dispatched BuildTask is an Attempt under the SAME mission."""

    @staticmethod
    def _attempt_for(session: BuildSession, task: BuildTask) -> AttemptContract:
        """The attempt the build path produces for one work item.

        Built through the existing adapter (``from_task_spec``) rather than a
        new one -- the point of the reconciliation is that no second attempt
        contract is minted for builds.
        """

        class _Spec:
            task_id = task.work_item_id
            instruction = task.objective
            base_revision = _ZERO_REVISION
            digest = _DIGEST_A
            target_paths = tuple(task.paths)

        return AttemptContract.from_task_spec(
            _Spec(),
            attempt_id=f"attempt-{task.work_item_id}",
            mission_id=task.mission_id,
            runtime_manifest_sha256=_DIGEST_B,
            policy_decision_sha256=_DIGEST_C,
            budget=ResourceBudget(max_wall_time_s=600),
            provenance=ContractProvenance(
                origin="daedalus.build_exec",
                source_revision=_ZERO_REVISION,
                created_at=_CREATED_AT,
                input_digests=(_DIGEST_A, _DIGEST_B, _DIGEST_C),
            ),
        )

    def test_the_attempt_names_the_sessions_mission(self):
        session = _session("alpha", "beta")
        mission = mission_contract_for_build_session(
            session,
            source_revision=_ZERO_REVISION,
            created_at=_CREATED_AT,
            budget=ResourceBudget(max_wall_time_s=600),
        )
        for task in session.tasks():
            attempt = self._attempt_for(session, task)
            self.assertEqual(attempt.mission_id, mission.mission_id)
            # The attempt's task_id IS the work item id: one identity across the
            # chain, not a build id translated into a spine id.
            self.assertEqual(attempt.task_id, task.work_item_id)
            self.assertIn(attempt.task_id, mission.work_item_ids)

    def test_a_wave_receipt_row_names_the_mission(self):
        """``build_exec`` puts the SAME dict into ``WaveResult.results`` that it
        hands to ``mark``, so stamping it here is what binds a wave receipt to
        its mission without a second receipt store."""
        session = _session("alpha")
        task = session.tasks()[0]
        row = {"status": "ok", "worker": "claude"}
        task.mark("landed", row)
        self.assertEqual(row["work_item"]["mission_id"], session.mission_id)
        self.assertEqual(row["work_item"]["work_item_id"], task.work_item_id)
        self.assertEqual(task.status, "landed")

    def test_an_unbound_task_leaves_the_row_unstamped(self):
        """An absent stamp reads as "nothing was bound", which is honest. A
        stamp naming the empty string would read as a mission."""
        task = _task("alpha")
        row = {"status": "ok"}
        task.mark("landed", row)
        self.assertNotIn("work_item", row)


class NoSecondKernelNoun(unittest.TestCase):
    """Invariant 1, structurally: build.py may REFERENCE the kernel's nouns and
    may not DEFINE one.

    Grep-based over the AST rather than over raw text, so a docstring
    explaining the mapping does not trip the guard while an actual
    ``class MissionLedger`` does.
    """

    #: The complete internal vocabulary build.py is allowed to define.
    # WorkItemIdentityError (ab0c92ce) is an ERROR raised by bind_work_items
    # when a re-plan would re-derive a bound id; it names the kernel noun to
    # say what it protects and defines no second vocabulary for it. The
    # reference rule below still holds for every other occurrence.
    ALLOWED_CLASSES = frozenset({"BuildTask", "Wave", "BuildSession",
                                 "WorkItemIdentityError"})

    #: Nouns that belong to the canonical kernel contracts.
    KERNEL_NOUNS = ("mission", "attempt", "evidence", "campaign", "receipt",
                    "artifact", "promotion", "workitem")

    #: Defined names that may CONTAIN a kernel noun, because each is a
    #: reference to the canonical id rather than a new thing.
    ALLOWED_REFERENCES = frozenset({"mission_id", "mission_id_for_session",
                                    "WorkItemIdentityError"})

    def setUp(self):
        self.tree = ast.parse(BUILD_PY.read_text(encoding="utf-8"))

    def _defined_names(self):
        """Every name build.py DEFINES: classes, functions, methods, their
        parameters, dataclass fields, and module/class-level constants."""
        names: set[str] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
                args = node.args
                for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                    names.add(arg.arg)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
        return names

    def test_build_py_defines_exactly_its_own_three_nouns(self):
        classes = {n.name for n in self.tree.body if isinstance(n, ast.ClassDef)}
        self.assertEqual(classes, set(self.ALLOWED_CLASSES))

    def test_build_py_defines_no_class_named_after_a_kernel_contract(self):
        offenders = [
            node.name
            for node in ast.walk(self.tree)
            if isinstance(node, ast.ClassDef)
            and any(noun in node.name.lower() for noun in self.KERNEL_NOUNS)
            and node.name not in self.ALLOWED_CLASSES
        ]
        self.assertEqual(offenders, [], (
            "build.py defines a class named after a canonical kernel contract; "
            "the kernel has one Mission/Attempt/Evidence vocabulary (Invariant 1)"
        ))

    def test_every_kernel_noun_in_build_py_is_a_reference_not_a_definition(self):
        offenders = sorted(
            name for name in self._defined_names()
            if any(noun in name.lower() for noun in self.KERNEL_NOUNS)
            and name not in self.ALLOWED_REFERENCES
        )
        self.assertEqual(offenders, [], (
            f"build.py defines {offenders}, which is a second kernel vocabulary. "
            "Allowed references to the canonical ids: "
            f"{sorted(self.ALLOWED_REFERENCES)}"
        ))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
