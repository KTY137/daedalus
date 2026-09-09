"""runner.py -- runs every Gate-3 arm under ONE manifest and refuses to lie
about what it produced.

This is the comparison runner packet §1 (G3-BASE-01) describes: it does not
introduce a second evaluation authority, a second budget rule, or a second
timing primitive. It composes the frozen contracts in ``contracts.py`` and the
one arm protocol in ``protocols.py`` (``run_trial`` measures wall time and
evaluator calls; this module never re-measures either).

EXPERIMENT (packet G3-BASE-01). The active delivery gate is 1. A
``ComparisonResult`` produced here is not Gate-3 baseline evidence until an
owner seals the ``RunManifest`` -- every result carries
``manifest.evidence_status()`` verbatim so nothing downstream can render it as
sealed evidence by omission.

Two refusals this module exists for, both learned from measured failures in
this repository (packet §3, ``docs/GATE2_FOREST_V2_TRIAGE.md``):

* **Unequal budgets never run.** ``RunManifest.__post_init__`` already calls
  ``require_equal_budgets`` at construction time, but ``RunManifest.budgets``
  is a ``Mapping`` reference, not a frozen copy -- a caller can still mutate
  the dict in place *after* construction. ``run_comparison`` re-checks before
  touching a single arm, so that mutation gap cannot let an unequal comparison
  start (packet rule R1 / test B1).
* **A killed run is never reported as complete.** ``run_trial`` (frozen,
  ``protocols.py``) only swallows an arm's *ordinary* failures into an errored
  ``TrialResult``; a ``FreezeError`` (a contract breach) or any
  non-``Exception`` interruption such as ``KeyboardInterrupt`` deliberately
  propagates. ``run_comparison`` catches exactly that escape, and instead of
  losing the partial progress or silently reporting success, returns a
  ``ComparisonResult`` with ``status="partial"`` naming every
  ``(arm, task_id, seed)`` cell that never produced a ``TrialResult`` --
  including cells belonging to arms that had not even started yet (packet
  test E5).

Setup fairness (task instruction, not a packet test id): ``protocols.Arm`` is
frozen and owned elsewhere in this packet, so it declares no setup/index-
building hook. Rather than time an arm's internal setup as part of its first
trial (charging that arm, and only that arm, for a cold start -- the same
starvation shape as splitting a budget, packet rule R1), this runner
recognises one OPTIONAL, non-protocol convention: an arm MAY expose a
``prepare(tasks) -> None`` method. If present, it is called exactly once per
arm, with the full shared task sequence, strictly BEFORE any of that arm's
timed trials, and it is never itself timed or budgeted. Every arm gets the
identical opportunity (called once, same tasks, before its own first trial);
an arm without ``prepare`` is unaffected. This is additive sugar over the
existing ``Arm`` protocol, not a change to it.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .contracts import FreezeError, RunManifest, SeedPolicy, TrialResult, require_equal_budgets
from .protocols import Arm, SealedEvaluator, Task, run_trial

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"

#: One planned unit of work: which arm, which task, which seed.
Cell = tuple[str, str, int]

_MIN_VERIFIABLE_REVISION_CHARS = 6


@dataclass(frozen=True)
class ComparisonResult:
    """Every ``TrialResult`` from one comparison run, grouped by arm, plus the
    honesty fields a report is required to carry.

    ``evidence_status`` is ``manifest.evidence_status()`` captured verbatim at
    the moment the run finished -- so a caller can render it without also
    holding a reference to the manifest, and so "UNSEALED ... NOT Gate-3
    baseline evidence" cannot be dropped by an incomplete render path.

    ``status`` is never ``"complete"`` while ``unrun_cells`` is non-empty, and
    never ``"partial"`` without at least one named cell -- both directions of
    that mismatch are exactly the defect this contract exists to make
    unrepresentable.
    """

    manifest: RunManifest
    trials_by_arm: Mapping[str, tuple[TrialResult, ...]]
    status: str
    evidence_status: str
    unrun_cells: tuple[Cell, ...] = ()
    partial_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in (STATUS_COMPLETE, STATUS_PARTIAL):
            raise FreezeError(f"unknown ComparisonResult.status {self.status!r}")
        if self.status == STATUS_COMPLETE and self.unrun_cells:
            raise FreezeError(
                "a run with unrun cells cannot report status='complete' -- "
                "that is precisely the silent-completeness defect this "
                "contract exists to refuse (G3-BASE-01 test E5)")
        if self.status == STATUS_PARTIAL and not self.unrun_cells:
            raise FreezeError(
                "status='partial' requires at least one named unrun cell; a "
                "partial claim with nothing named as unrun is not evidence "
                "of what did not run")

    @property
    def all_trials(self) -> tuple[TrialResult, ...]:
        """Every trial across every arm, in stable (sorted-by-arm) order."""
        return tuple(
            trial
            for arm_name in sorted(self.trials_by_arm)
            for trial in self.trials_by_arm[arm_name]
        )


def _seeds_for_arm(arm: Arm, seed_policy: SeedPolicy) -> tuple[int, ...]:
    """Packet rule (task instruction): a stochastic arm runs under the full
    seed list; a deterministic arm runs once, on the policy's first seed.

    An arm that declares ``stochastic=True`` while the manifest's
    ``SeedPolicy`` does not actually carry enough seeds is refused here,
    loudly, rather than silently run once -- that mismatch is exactly the
    defect ``SeedPolicy.MIN_STOCHASTIC_SEEDS`` exists to prevent (plan §14,
    G3-BASE-01 test E4).
    """
    if not arm.stochastic:
        return (seed_policy.seeds[0],)
    seeds = seed_policy.seeds
    if len(seeds) < SeedPolicy.MIN_STOCHASTIC_SEEDS:
        raise FreezeError(
            f"arm {arm.name!r} declares stochastic=True but this run's "
            f"SeedPolicy carries only {len(seeds)} seed(s) "
            f"(need >= {SeedPolicy.MIN_STOCHASTIC_SEEDS}); running a "
            "stochastic arm on too few seeds hides the variance the seeds "
            "exist to measure (plan §14; G3-BASE-01 rule and test E4).")
    return seeds


def run_comparison(
    arms: Sequence[Arm],
    tasks: Sequence[Task],
    manifest: RunManifest,
    evaluator_factory: Callable[[], SealedEvaluator],
) -> ComparisonResult:
    """Run every arm over every task under one ``RunManifest``.

    Order of operations, all before a single trial executes:

    1. Re-check ``require_equal_budgets(manifest.budgets)`` (R1/B1) -- defense
       against post-construction mutation of the budgets mapping, see module
       docstring.
    2. Sort arms by name (deterministic output order).
    3. Resolve each arm's budget and seed list, refusing (``FreezeError``,
       before anything runs) an arm with no declared budget or a stochastic
       arm under too few seeds.
    4. Build the full ``(arm, task, seed)`` plan.

    Then run the plan in order. Each cell gets a FRESH ``SealedEvaluator``
    from ``evaluator_factory()`` -- never shared across trials, so an
    evaluator call budget or any evaluator-held state cannot leak from one
    trial into the next. Timing and call-counting are ``run_trial``'s job
    (frozen, ``protocols.py``); this function never re-measures either.

    If anything escapes ``run_trial`` -- a ``FreezeError`` (a contract
    breach: a sealed-evaluator violation, a refused budget split, an arm
    returning neither success nor error) or a ``KeyboardInterrupt`` (the run
    was killed) -- the run stops immediately and this function returns a
    ``ComparisonResult`` with ``status="partial"`` naming every cell that had
    not yet produced a ``TrialResult``, instead of raising and losing the
    completed trials, and instead of returning as if the run had finished.
    """
    require_equal_budgets(manifest.budgets)

    ordered_arms = sorted(arms, key=lambda a: a.name)
    if not ordered_arms:
        raise FreezeError("run_comparison was given no arms to run")

    plan: list[tuple[Arm, Task, int]] = []
    for arm in ordered_arms:
        if arm.name not in manifest.budgets:
            raise FreezeError(
                f"arm {arm.name!r} has no ArmBudget entry in this manifest; "
                "an arm cannot run without a declared, budget-equal "
                "allotment (packet rule R1)")
        seeds = _seeds_for_arm(arm, manifest.seed_policy)
        for task in tasks:
            for seed in seeds:
                plan.append((arm, task, seed))

    trials_by_arm: dict[str, list[TrialResult]] = {a.name: [] for a in ordered_arms}
    prepared: set[str] = set()
    completed: set[Cell] = set()

    try:
        for arm, task, seed in plan:
            prepare = getattr(arm, "prepare", None)
            if callable(prepare) and arm.name not in prepared:
                prepare(tasks)  # untimed, unbudgeted, once per arm -- see module docstring
                prepared.add(arm.name)

            budget = manifest.budgets[arm.name]
            evaluator = evaluator_factory()
            result = run_trial(arm, task, budget, evaluator, seed)
            trials_by_arm[arm.name].append(result)
            completed.add((arm.name, task.task_id, seed))
    except (Exception, KeyboardInterrupt) as exc:
        unrun = tuple(
            (a.name, t.task_id, s)
            for a, t, s in plan
            if (a.name, t.task_id, s) not in completed
        )
        return ComparisonResult(
            manifest=manifest,
            trials_by_arm={name: tuple(rows) for name, rows in trials_by_arm.items()},
            status=STATUS_PARTIAL,
            evidence_status=manifest.evidence_status(),
            unrun_cells=unrun,
            partial_reason=f"{type(exc).__name__}: {exc}",
        )

    return ComparisonResult(
        manifest=manifest,
        trials_by_arm={name: tuple(rows) for name, rows in trials_by_arm.items()},
        status=STATUS_COMPLETE,
        evidence_status=manifest.evidence_status(),
    )


def verify_base_revision(manifest: RunManifest, repo_root: str | Path) -> None:
    """E3: refuse when ``manifest.base_revision`` does not match the git
    revision actually checked out at ``repo_root``.

    A result attributed to the wrong revision is unreproducible (plan
    invariants 6 and 7). This must be checked before a run is trusted as
    evidence, so it raises ``FreezeError`` rather than returning a flag a
    caller could ignore.

    ``repo_root`` need not be a repository's top level -- ``git rev-parse``
    resolves ``HEAD`` from any directory inside a working tree. A directory
    that is not inside any git working tree (or where ``git`` cannot be
    invoked at all) is refused cleanly with ``FreezeError``, never a raw
    ``subprocess`` exception or a silent pass.
    """
    root = str(repo_root)
    declared = manifest.base_revision.strip()
    if len(declared) < _MIN_VERIFIABLE_REVISION_CHARS:
        raise FreezeError(
            f"manifest.base_revision {declared!r} is too short "
            f"(< {_MIN_VERIFIABLE_REVISION_CHARS} hex chars) to verify "
            "unambiguously against a live git revision")

    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FreezeError(
            f"could not invoke git in {root!r} to verify manifest.base_revision "
            f"{declared!r}: {type(exc).__name__}: {exc}"
        ) from exc

    if proc.returncode != 0:
        raise FreezeError(
            f"{root!r} is not a readable git checkout (git rev-parse HEAD "
            f"exited {proc.returncode}: {proc.stderr.strip()!r}); cannot "
            f"verify manifest.base_revision {declared!r} against it "
            "(plan invariant 6: a result attributed to the wrong revision "
            "is unreproducible).")

    current = proc.stdout.strip()
    if not (current.startswith(declared) or declared.startswith(current)):
        raise FreezeError(
            f"stale base revision: manifest declares {declared!r} but "
            f"{root!r} is currently checked out at {current!r}. A run "
            "against the wrong revision is not reproducible evidence (plan "
            "invariant 6/7) and must be refused before anything runs.")
