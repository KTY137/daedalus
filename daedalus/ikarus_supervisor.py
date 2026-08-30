# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The Ikarus supervisor: one mission, one shared state ledger, role attempts.

WHAT THIS IS. The reusable half of what ``daedalus/ignition/gate1.py`` proved
as a fixture: intent -> ``MissionContract`` -> ordered work items -> attempts,
driven by a supervisor that keeps a SHARED STATE LEDGER — the coordination
object Agentic-J (arXiv 2606.02080, §3.1) puts at the centre of its system and
the master plan §7 already prescribes as artifact-first coordination
(``ProductSpec -> … -> MissionContract -> WorkItems -> Attempts -> Artifacts``).
Work packet: ``docs/work-packets/G1-IKARUS-01-supervisor-slice.md``.

WHAT THE LEDGER IS, PRECISELY — because "ledger" is a loaded word in this
tree.  It is NOT a second event store (invariant 1 has exactly one spine, and
review rule one calls a second one release-blocking).  It is a PROJECTION:
every state change writes one immutable, content-addressed revision file, and
each revision names ``previous_ledger_sha256``, so the chain is append-only
and tamper-evident without ever being authoritative.  The truth stays where it
already lives — the ``MissionContract``, the ``AttemptReceipt``s and the spine
ledger the attempts already write.  Deleting the whole ledger directory loses
a convenient view and no fact.

WHAT THE SUPERVISOR IS NOT, in v1, on purpose:

* not an LLM.  Planning is caller-declared work items, the same reviewable-
  draft posture ``ikarus_chat`` v1 took.  A model may PROPOSE plans later; the
  contract layer here does not change when it does.
* not a chat.  It accepts no transcript and stores none — the ledger carries
  the objective string and typed status, nothing conversational (plan §7:
  "Chat is an interface, not orchestration state").
* not a door.  There is no CLI tail and no module-level effect; every write
  lands under the caller-supplied run directory, and the attempts themselves
  go through ``TaskAttempt`` — the same guarded path everything else uses.
  Wiring a provider-backed role arrives with caller-injection half two, not
  here.

ROLES.  Agentic-J gives each subagent a targeted toolset; here a role is a
:class:`RoleHarness` — a runner factory and a gate factory keyed by name.  The
supervisor refuses a plan naming a role it was not given BEFORE any attempt
starts, because "the registry did not know it" must never be discovered
halfway through a half-executed mission.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from .build import BuildSession, BuildTask, Wave, mission_id_for_session
from .ikarus_runtime_role import (
    INPROCESS_RUNTIME_ID,
    RuntimeRoleRegistry,
    RuntimeRoleSnapshot,
)
from .schemas import (
    MissionContract,
    ResourceBudget,
    derive_work_item_id,
    work_item_identity_sha256,
)
from .spine.attempt import (
    GateResult,
    RunnerContext,
    TaskAttempt,
    TaskSpec,
    TaskSpecInvalid,
)
from .spine.receipts import mission_contract_for_build_session

LEDGER_SCHEMA = "daedalus-ikarus-state-ledger/2"

#: Terminal work-item states the ledger may carry.  A coarse lifecycle on
#: purpose, mirroring ``BuildTask.status`` — anything finer rides on the
#: attempt result, which the revision references by digest instead of copying.
_ITEM_STATES = ("planned", "dispatched", "landed", "bounced", "skipped", "refused")


class SupervisorRefused(RuntimeError):
    """The mission cannot start (or continue) and the reason is named."""


class StateLedgerBroken(RuntimeError):
    """The revision chain on disk does not verify."""


@dataclass(frozen=True)
class RoleHarness:
    """What one role is allowed to bring to an attempt.

    ``runner_factory(item)`` returns the ``runner(ctx)`` callable and
    ``gate_factory(item)`` the ``gate(ctx)`` callable that
    :class:`TaskAttempt` consumes.  Factories rather than callables so a role
    can specialise per work item (Agentic-J's coder consults per-plugin
    skills; ours consults the item) without the supervisor knowing how.
    """

    role: str
    runner_factory: Callable[["PlannedItem"], Callable[[Any], dict]]
    gate_factory: Callable[["PlannedItem"], Callable[[Any], GateResult]]


@dataclass(frozen=True)
class PlannedItem:
    """One caller-declared work item: what, where, and which role does it."""

    objective: str
    role: str
    paths: tuple[str, ...]
    gate_paths: tuple[str, ...] = ()
    runtime_id: str = INPROCESS_RUNTIME_ID

    def __post_init__(self) -> None:
        if not str(self.objective).strip():
            raise ValueError("a planned item needs a non-empty objective")
        if not str(self.role).strip():
            raise ValueError("a planned item needs a role")
        if not self.paths:
            raise ValueError("a planned item must declare its target paths")
        if not isinstance(self.runtime_id, str) or not self.runtime_id.strip():
            raise ValueError("a planned item needs a runtime_id")
        object.__setattr__(self, "paths", tuple(str(p) for p in self.paths))
        object.__setattr__(self, "gate_paths", tuple(str(p) for p in self.gate_paths))
        object.__setattr__(self, "runtime_id", self.runtime_id.strip())


@dataclass(frozen=True)
class _TaskPlanSnapshot:
    """Caller-owned BuildTask primitives captured before any runner executes."""

    mission_id: str
    work_item_id: str
    work_item_identity_sha256: str
    objective: str
    agent: str
    paths: tuple[str, ...]
    builder: str


def _snapshot_planned_items(
    items: Sequence[PlannedItem],
) -> tuple[PlannedItem, ...]:
    if isinstance(items, (str, bytes)):
        raise SupervisorRefused("planned items must be a sequence of objects")
    try:
        return tuple(
            PlannedItem(
                objective=item.objective,
                role=item.role,
                paths=tuple(item.paths),
                gate_paths=tuple(item.gate_paths),
                runtime_id=item.runtime_id,
            )
            for item in items
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise SupervisorRefused("planned items are malformed") from exc


def _snapshot_callback_task(task: TaskSpec) -> TaskSpec:
    """Give injected code a value-equivalent copy, never the evidence object."""

    metadata = json.loads(_canonical(dict(task.metadata)))
    correctness_before_state = json.loads(
        _canonical(dict(task.correctness_before_state))
    )
    return TaskSpec(
        task_id=str(task.task_id),
        instruction=str(task.instruction),
        base_revision=(
            None if task.base_revision is None else str(task.base_revision)
        ),
        gate_paths=tuple(str(path) for path in task.gate_paths),
        metadata=MappingProxyType(metadata),
        target_paths=tuple(str(path) for path in task.target_paths),
        gate_argv=tuple(str(arg) for arg in task.gate_argv),
        gate_cwd=str(task.gate_cwd),
        gate_timeout_s=float(task.gate_timeout_s),
        fail_to_pass=tuple(str(test) for test in task.fail_to_pass),
        pass_to_pass=tuple(str(test) for test in task.pass_to_pass),
        gate_criterion_paths=tuple(
            str(path) for path in task.gate_criterion_paths
        ),
        gate_reads_scope=bool(task.gate_reads_scope),
        correctness_before_state=MappingProxyType(correctness_before_state),
    )


def _snapshot_callback_context(
    context: RunnerContext,
    task_template: TaskSpec,
) -> RunnerContext:
    """Isolate callback mutation from TaskAttempt's canonical TaskSpec."""

    return RunnerContext(
        worktree=Path(context.worktree),
        branch=str(context.branch),
        base_revision=str(context.base_revision),
        task=_snapshot_callback_task(task_template),
        is_cancelled=context.is_cancelled,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(body: Mapping[str, Any]) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _runtime_binding(
    item: PlannedItem,
    runtime_roles: RuntimeRoleRegistry | None,
) -> RuntimeRoleSnapshot | None:
    if item.runtime_id == INPROCESS_RUNTIME_ID or runtime_roles is None:
        return None
    return runtime_roles.snapshot(item.role, item.runtime_id)


def _resolve_runtime_bindings(
    items: Sequence[PlannedItem],
    runtime_roles: RuntimeRoleRegistry | None,
) -> tuple[RuntimeRoleSnapshot | None, ...]:
    if runtime_roles is not None and type(runtime_roles) is not RuntimeRoleRegistry:
        raise SupervisorRefused(
            "runtime_roles must be an exact immutable RuntimeRoleRegistry"
        )
    return tuple(_runtime_binding(item, runtime_roles) for item in items)


def _task_builder(
    item: PlannedItem,
    binding: RuntimeRoleSnapshot | None,
) -> str:
    if item.runtime_id == INPROCESS_RUNTIME_ID:
        return f"role:{item.role}"
    # Keep the FULL digest in the session snapshot. The mission slug may use a
    # display prefix, but this is the only structural field BuildTask offers
    # for the selected builder and must not make drift diagnosis depend on a
    # truncated identity.
    suffix = binding.digest if binding is not None else "unresolved"
    return f"role:{item.role}@runtime:{item.runtime_id}:{suffix}"


def _planned_runtime_binding_sha256(
    task: _TaskPlanSnapshot,
    item: PlannedItem,
) -> str | None:
    if item.runtime_id == INPROCESS_RUNTIME_ID:
        return None
    prefix = f"role:{item.role}@runtime:{item.runtime_id}:"
    if not task.builder.startswith(prefix):
        return None
    value = task.builder[len(prefix):]
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        return None
    return value


def _plan_item_identity(
    item: PlannedItem,
    binding: RuntimeRoleSnapshot | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "objective": item.objective,
        "role": item.role,
        "paths": list(item.paths),
    }
    # Preserve every legacy in-process mission id byte-for-byte. Runtime
    # identity joins the plan only when the caller explicitly selects a
    # variable backend.
    if item.runtime_id != INPROCESS_RUNTIME_ID:
        if item.gate_paths:
            body["gate_paths"] = list(item.gate_paths)
        body["runtime_id"] = item.runtime_id
        body["runtime_binding_sha256"] = binding.digest if binding else None
    return body


def _plan_digest(
    objective: str,
    items: Sequence[PlannedItem],
    bindings: Sequence[RuntimeRoleSnapshot | None],
) -> str:
    if len(items) != len(bindings):
        raise SupervisorRefused("runtime binding count does not match planned items")
    return hashlib.sha256(
        _canonical(
            {
                "objective": objective,
                "items": [
                    _plan_item_identity(item, binding)
                    for item, binding in zip(items, bindings)
                ],
            }
        ).encode("utf-8")
    ).hexdigest()


# --------------------------------------------------------------------------- #
# the state ledger                                                             #
# --------------------------------------------------------------------------- #
class StateLedger:
    """Immutable, chained revisions of one mission's coordination state.

    Every :meth:`publish` writes ``<dir>/<seq:04d>-<digest12>.json`` holding
    the FULL state at that moment plus ``previous_ledger_sha256`` — full
    snapshots, not deltas, so a reader needs one file to know where the
    mission stands and the chain only to know nobody rewrote history.
    ``revision_sha256`` is over the body with the digest field removed, the
    same recipe every receipt in this tree uses.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._sequence = 0
        self._previous = ""

    def publish(self, state: Mapping[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schema": LEDGER_SCHEMA,
            "sequence": self._sequence,
            "previous_ledger_sha256": self._previous,
            "published_at": _utc_now(),
            **{k: v for k, v in state.items()},
        }
        digest = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
        body["revision_sha256"] = digest
        path = self.directory / f"{self._sequence:04d}-{digest[:12]}.json"
        # ``x`` so a sequence collision (two supervisors on one directory) is
        # a loud error instead of one silently absorbing the other's history.
        with path.open("x", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False))
            fh.write("\n")
        self._sequence += 1
        self._previous = digest
        return body


def verify_state_ledger(directory: str | Path) -> tuple[dict[str, Any], ...]:
    """Re-derive every digest and re-walk the chain; return the revisions.

    Raises :class:`StateLedgerBroken` on a tampered body, a broken link, a
    gap, or an empty directory — an empty ledger is "could not verify", never
    "verified, nothing there".
    """

    directory = Path(directory)
    paths = sorted(directory.glob("[0-9][0-9][0-9][0-9]-*.json"))
    if not paths:
        raise StateLedgerBroken(f"no ledger revisions under {directory}")
    revisions: list[dict[str, Any]] = []
    previous = ""
    for expected_seq, path in enumerate(paths):
        body = json.loads(path.read_text(encoding="utf-8"))
        claimed = str(body.get("revision_sha256", ""))
        subject = {k: v for k, v in body.items() if k != "revision_sha256"}
        derived = hashlib.sha256(_canonical(subject).encode("utf-8")).hexdigest()
        if derived != claimed:
            raise StateLedgerBroken(f"{path.name}: body does not match its digest")
        if int(body.get("sequence", -1)) != expected_seq:
            raise StateLedgerBroken(
                f"{path.name}: sequence {body.get('sequence')} where "
                f"{expected_seq} was expected — a revision is missing or reordered"
            )
        if str(body.get("previous_ledger_sha256", "")) != previous:
            raise StateLedgerBroken(f"{path.name}: chain link does not match")
        previous = claimed
        revisions.append(body)
    return tuple(revisions)


# --------------------------------------------------------------------------- #
# planning: caller intent -> canonical mission                                 #
# --------------------------------------------------------------------------- #
def plan_mission(
    objective: str,
    *,
    repo_root: str | Path,
    items: Sequence[PlannedItem],
    base_revision: str,
    budget: ResourceBudget,
    success_criteria: Sequence[str],
    project: str = "ikarus-supervisor",
    trace_id: str | None = None,
    runtime_roles: RuntimeRoleRegistry | None = None,
) -> tuple[BuildSession, MissionContract]:
    """Compile intent into the one session/mission pair the kernel accepts.

    Nothing here is invented: ``BuildSession.__post_init__`` binds the
    deterministic ``mission_id`` and one ``work_item_id`` per task (same plan,
    same ids — that is what makes reruns comparable), and
    ``mission_contract_for_build_session`` binds the effect-registry policy
    digest, so the mission and its attempts name ONE policy.  ``created=""``
    for the reason the ignition slice documents: an id that moves with the
    clock cannot be replayed.
    """

    items = _snapshot_planned_items(items)
    if not items:
        raise SupervisorRefused("a mission with no work items is not a mission")
    # THE SLUG IS A FUNCTION OF THE PLAN, and this line exists because the
    # first acceptance run proved the obvious default wrong: a static slug
    # plus ``created=""`` means EVERY supervisor mission is
    # ``mission-ikarus-supervisor`` — two unrelated plans sharing one mission
    # identity, which is exactly the collision ``mission_id_for_session``'s
    # own docstring warns about ("a caller that cares supplies mission_id").
    # A timestamp would fix uniqueness and break replay; a content digest
    # gives both: same plan -> same id, different plan -> different id.
    bindings = _resolve_runtime_bindings(items, runtime_roles)
    plan_digest = _plan_digest(objective, items, bindings)
    tasks = [
        BuildTask(
            objective=item.objective,
            agent="daedalus.ikarus_supervisor",
            category="renovation",
            lane="deterministic",
            tier="none",
            builder=_task_builder(item, binding),
            frontier=False,
            paths=list(item.paths),
        )
        for item, binding in zip(items, bindings)
    ]
    session = BuildSession(
        feature=objective,
        repo_root=str(Path(repo_root).resolve()),
        project=project,
        waves=[Wave(index=0, tasks=tasks)],
        slug=f"ikarus-{plan_digest[:12]}",
        created="",
        max_workers=1,
    )
    mission = mission_contract_for_build_session(
        session,
        source_revision=base_revision,
        created_at=_utc_now(),
        budget=budget,
        success_criteria=tuple(success_criteria),
        trace_id=trace_id or session.mission_id,
    )
    return session, mission


# --------------------------------------------------------------------------- #
# the supervisor                                                               #
# --------------------------------------------------------------------------- #
@dataclass
class MissionSupervisor:
    """Drive one planned mission through role attempts, ledger revision by
    ledger revision.

    ``roles`` is the complete pre-existing harness mapping this mission may
    use. Legacy in-process entries are keyed by role. Variable runtime entries
    are keyed by :attr:`RuntimeRoleBinding.harness_key`, so an explicit runtime
    can never fall back to a role-only callable. The whole plan is checked
    before the first dispatch.
    """

    repo_root: Path
    run_dir: Path
    roles: Mapping[str, RoleHarness]
    gate_timeout_s: float = 300.0
    fail_fast: bool = True
    #: Populated by :meth:`run`.
    results: list[Any] = field(default_factory=list)
    # Appended after every legacy constructor field so existing positional
    # calls retain their original meaning. New callers should use the keyword.
    runtime_roles: RuntimeRoleRegistry | None = None

    def run(
        self,
        session: BuildSession,
        mission: MissionContract,
        items: Sequence[PlannedItem],
    ) -> dict[str, Any]:
        # MissionContract is caller-owned even though it is frozen. Snapshot
        # and revalidate its complete canonical body before any caller-owned
        # registry or harness lookup can run Python code. From here onward the
        # live ``mission`` object is never consulted again.
        if type(mission) is not MissionContract:
            raise SupervisorRefused("mission must be an exact MissionContract")
        try:
            supplied_mission_sha256 = str(mission.digest)
            mission_snapshot = MissionContract.from_dict(mission.to_dict())
        except (AttributeError, TypeError, ValueError) as exc:
            raise SupervisorRefused(
                "mission contract could not be snapshotted and validated"
            ) from exc
        mission_sha256 = mission_snapshot.digest
        if mission_sha256 != supplied_mission_sha256:
            raise SupervisorRefused(
                "mission contract changed while its canonical snapshot was captured"
            )
        mission_body = mission_snapshot.to_dict()
        mission_id = str(mission_snapshot.mission_id)
        mission_objective = str(mission_snapshot.objective)
        mission_source_revision = str(mission_snapshot.source_revision)
        mission_work_item_ids = tuple(mission_snapshot.work_item_ids)
        mission_policy_sha256 = str(mission_snapshot.policy_sha256)
        mission_budget = ResourceBudget(
            max_tokens=mission_snapshot.budget.max_tokens,
            max_cost_microusd=mission_snapshot.budget.max_cost_microusd,
            max_wall_time_s=mission_snapshot.budget.max_wall_time_s,
            max_attempts=mission_snapshot.budget.max_attempts,
        )

        # Snapshot caller-owned frozen dataclasses before any runner is handed
        # control. ``frozen=True`` prevents accidental assignment; it does not
        # make object.__setattr__ a security boundary across a multi-item run.
        items = _snapshot_planned_items(items)
        try:
            execution_root = Path(self.repo_root).resolve()
            run_dir = Path(self.run_dir).resolve()
            gate_timeout_s = float(self.gate_timeout_s)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise SupervisorRefused(
                "supervisor repository/run paths or timeout could not be resolved"
            ) from exc
        if gate_timeout_s <= 0 or not math.isfinite(gate_timeout_s):
            raise SupervisorRefused("supervisor gate timeout must be positive and finite")
        if type(self.fail_fast) is not bool:
            raise SupervisorRefused("supervisor fail_fast setting must be boolean")
        fail_fast = self.fail_fast
        result_sink = self.results
        if len(session.waves) != 1:
            raise SupervisorRefused(
                "the Ikarus runtime port requires exactly one ordered work wave"
            )
        tasks = tuple(session.waves[0].tasks)
        if any(type(task) is not BuildTask for task in tasks):
            raise SupervisorRefused(
                "session tasks must be exact BuildTask records"
            )
        task_plans = tuple(
            _TaskPlanSnapshot(
                mission_id=str(task.mission_id),
                work_item_id=str(task.work_item_id),
                work_item_identity_sha256=str(
                    task.work_item_identity_sha256
                ),
                objective=str(task.objective),
                agent=str(task.agent),
                paths=tuple(str(path) for path in task.paths),
                builder=str(task.builder),
            )
            for task in tasks
        )
        if len(tasks) != len(items):
            raise SupervisorRefused(
                f"plan drift: session carries {len(tasks)} tasks for "
                f"{len(items)} planned items"
            )
        bindings = _resolve_runtime_bindings(items, self.runtime_roles)
        expected_plan_digest = _plan_digest(session.feature, items, bindings)
        expected_slug = f"ikarus-{expected_plan_digest[:12]}"
        expected_mission_id = mission_id_for_session(
            expected_slug, session.created
        )
        if session.slug != expected_slug or session.mission_id != expected_mission_id:
            raise SupervisorRefused(
                "plan identity drift: supplied items/runtime bindings do not "
                "derive the session mission"
            )
        if session.mission_id != mission_id:
            raise SupervisorRefused(
                "session/mission drift: session mission_id does not match the "
                "MissionContract"
            )
        for ordinal, task_plan in enumerate(task_plans):
            identity = (
                task_plan.objective,
                task_plan.agent,
                *sorted(task_plan.paths),
            )
            expected_identity_sha256 = work_item_identity_sha256(
                mission_id,
                ordinal=ordinal,
                identity=identity,
            )
            expected_work_item_id = derive_work_item_id(
                mission_id,
                ordinal=ordinal,
                identity=identity,
            )
            if (
                task_plan.mission_id != mission_id
                or task_plan.work_item_identity_sha256
                != expected_identity_sha256
                or task_plan.work_item_id != expected_work_item_id
            ):
                raise SupervisorRefused(
                    "session work item identity drift: ordinal, mission, "
                    "substance digest and work_item_id must derive together"
                )
        session_work_items = tuple(
            sorted(task_plan.work_item_id for task_plan in task_plans)
        )
        if session_work_items != mission_work_item_ids:
            raise SupervisorRefused(
                "session/mission drift: work item ids do not match the "
                "MissionContract"
            )
        if session.feature != mission_objective:
            raise SupervisorRefused(
                "session/mission drift: objective does not match the "
                "MissionContract"
            )
        try:
            planned_root = Path(session.repo_root).resolve()
            # execution_root was snapshotted before any caller code can run.
        except (OSError, RuntimeError, ValueError) as exc:
            raise SupervisorRefused(
                "session repository root could not be resolved"
            ) from exc
        if planned_root != execution_root:
            raise SupervisorRefused(
                "session/supervisor drift: repository root does not match"
            )

        contract_path = run_dir / "mission.json"
        if contract_path.exists():
            try:
                retained = MissionContract.from_dict(
                    json.loads(contract_path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise SupervisorRefused(
                    "existing mission.json is malformed and cannot be reused"
                ) from exc
            if retained.digest != mission_sha256:
                raise SupervisorRefused(
                    "existing mission.json belongs to a different mission"
                )

        # REFUSE THE WHOLE PLAN FIRST. One pass over every role/runtime pair
        # before any attempt exists; the refusal lands in the ledger so a
        # reader of the run directory sees WHY nothing ran. An explicit
        # runtime NEVER falls back to the legacy role map.
        ledger = StateLedger(run_dir / "ledger")
        resolutions: list[
            tuple[
                Callable[[PlannedItem], Callable[[Any], dict]] | None,
                Callable[[PlannedItem], Callable[[Any], GateResult]] | None,
                RuntimeRoleSnapshot | None,
                str | None,
            ]
        ] = []
        for task_plan, item, binding in zip(task_plans, items, bindings):
            if (
                task_plan.objective != item.objective
                or task_plan.paths != item.paths
            ):
                resolutions.append(
                    (
                        None,
                        None,
                        None,
                        "work item substance drifted after planning: objective "
                        "or target paths changed",
                    )
                )
                continue
            if item.runtime_id == INPROCESS_RUNTIME_ID:
                harness = self.roles.get(item.role)
                if task_plan.builder != _task_builder(item, None):
                    error = "role binding drifted after planning"
                elif harness is None:
                    error = f"role {item.role!r} is not in the harness registry"
                elif type(harness) is not RoleHarness or harness.role != item.role:
                    error = f"role {item.role!r} has a malformed RoleHarness binding"
                    harness = None
                elif not callable(harness.runner_factory) or not callable(
                    harness.gate_factory
                ):
                    error = f"role {item.role!r} has non-callable harness factories"
                    harness = None
                else:
                    error = None
                resolutions.append(
                    (
                        harness.runner_factory if harness is not None else None,
                        harness.gate_factory if harness is not None else None,
                        None,
                        error,
                    )
                )
                continue

            if binding is None:
                resolutions.append(
                    (
                        None,
                        None,
                        None,
                        "runtime-role binding is not registered: "
                        f"role={item.role!r} runtime_id={item.runtime_id!r}",
                    )
                )
                continue
            expected_builder = _task_builder(item, binding)
            if task_plan.builder != expected_builder:
                resolutions.append(
                    (
                        None,
                        None,
                        binding,
                        "runtime-role binding drifted after planning: "
                        f"planned={task_plan.builder!r} current={expected_builder!r}",
                    )
                )
                continue
            if not binding.executable:
                resolutions.append(
                    (
                        None,
                        None,
                        binding,
                        f"runtime {item.runtime_id!r} is {binding.execution_mode}: "
                        f"{binding.refusal_reason}",
                    )
                )
                continue
            harness = self.roles.get(binding.harness_key)
            if harness is None:
                resolutions.append(
                    (
                        None,
                        None,
                        binding,
                        "executable fixture has no exact injected RoleHarness: "
                        f"key={binding.harness_key!r}",
                    )
                )
                continue
            if type(harness) is not RoleHarness or harness.role != item.role:
                resolutions.append(
                    (
                        None,
                        None,
                        binding,
                        "runtime-role fixture has a malformed or role-mismatched "
                        "RoleHarness",
                    )
                )
                continue
            if not callable(harness.runner_factory) or not callable(
                harness.gate_factory
            ):
                resolutions.append(
                    (
                        None,
                        None,
                        binding,
                        "runtime-role fixture has non-callable harness factories",
                    )
                )
                continue
            resolutions.append(
                (
                    harness.runner_factory,
                    harness.gate_factory,
                    binding,
                    None,
                )
            )

        # Construct every TaskSpec during whole-plan preflight. Path
        # normalization/refusal must not happen after a row already says
        # "dispatched", and a malformed later item must stop the mission before
        # an earlier fixture is allowed to run.
        specs: list[TaskSpec | None] = []
        callback_task_templates: list[TaskSpec | None] = []
        for index, (task_plan, item, resolution) in enumerate(
            zip(task_plans, items, resolutions)
        ):
            runner_factory, gate_factory, binding, error = resolution
            if error is not None:
                specs.append(None)
                callback_task_templates.append(None)
                continue
            runtime_metadata = {}
            if binding is not None:
                runtime_metadata = {
                    "runtime_binding_schema": binding.schema,
                    "runtime_id": binding.runtime_id,
                    "runtime_binding_sha256": binding.digest,
                    "runtime_adapter_id": binding.adapter_id,
                    "runtime_adapter_version": binding.adapter_version,
                    "runtime_source_revision": binding.source_revision,
                    "runtime_origin": binding.origin,
                    "runtime_execution_mode": binding.execution_mode,
                }
            try:
                spec = TaskSpec(
                    task_id=task_plan.work_item_id,
                    instruction=task_plan.objective,
                    base_revision=mission_source_revision,
                    target_paths=task_plan.paths,
                    gate_paths=item.gate_paths,
                    gate_timeout_s=gate_timeout_s,
                    metadata=MappingProxyType({
                        "mission_id": mission_id,
                        "work_item_id": task_plan.work_item_id,
                        "role": item.role,
                        "operator": "daedalus.ikarus_supervisor",
                        **runtime_metadata,
                    }),
                )
            except TaskSpecInvalid as exc:
                resolutions[index] = (
                    None,
                    None,
                    binding,
                    f"task declaration refused before dispatch: {exc}",
                )
                specs.append(None)
                callback_task_templates.append(None)
                continue
            specs.append(spec)
            callback_template = _snapshot_callback_task(spec)
            if callback_template.digest != spec.digest:
                resolutions[index] = (
                    None,
                    None,
                    binding,
                    "callback TaskSpec snapshot changed the planned task digest",
                )
                specs[index] = None
                callback_task_templates.append(None)
                continue
            callback_task_templates.append(callback_template)

        rows = []
        for task_plan, item, _resolution in zip(task_plans, items, resolutions):
            rows.append({
                "work_item_id": task_plan.work_item_id,
                "objective": item.objective,
                "role": item.role,
                "runtime_id": item.runtime_id,
                "runtime_binding_sha256": _planned_runtime_binding_sha256(
                    task_plan, item
                ),
                "paths": list(item.paths),
                "status": "planned",
                "attempt_id": None,
                "attempt_receipt_sha256": None,
                "evidence_packet_sha256": None,
                "detail": None,
            })
        base = {
            "mission_id": mission_id,
            "mission_sha256": mission_sha256,
            "objective": mission_objective,
            "source_revision": mission_source_revision,
            "items": rows,
            "outcome": None,
        }
        # The mission contract itself is retained beside the ledger — the
        # ledger references it by digest and never restates it.
        if not contract_path.exists():
            contract_path.write_text(
                json.dumps(mission_body, indent=1, sort_keys=True),
                encoding="utf-8",
                newline="\n",
            )
        ledger.publish(base)

        preflight_errors = [
            error for _, _, _, error in resolutions if error is not None
        ]
        if preflight_errors:
            for row, (_, _, _, error) in zip(rows, resolutions):
                if error is not None:
                    row["status"] = "refused"
                    row["detail"] = error
                else:
                    row["status"] = "skipped"
                    row["detail"] = "mission refused before dispatch"
            base["outcome"] = "refused"
            ledger.publish(base)
            raise SupervisorRefused(
                "the plan has unresolved runtime-role bindings: "
                + " | ".join(preflight_errors)
            )

        outcome = "landed"
        for index, (
            task,
            task_plan,
            item,
            (runner_factory, gate_factory, binding, _),
            spec,
            callback_task_template,
        ) in enumerate(
            zip(
                tasks,
                task_plans,
                items,
                resolutions,
                specs,
                callback_task_templates,
            )
        ):
            if outcome != "landed" and fail_fast:
                task.status = "planned"
                rows[index]["status"] = "skipped"
                rows[index]["detail"] = "fail-fast: an earlier work item bounced"
                ledger.publish(base)
                continue
            if (
                runner_factory is None
                or gate_factory is None
                or spec is None
                or callback_task_template is None
            ):
                raise SupervisorRefused("runtime-role resolution disappeared")
            rows[index]["status"] = task.status = "dispatched"
            ledger.publish(base)

            # Factory evaluation is itself caller code. Keep it lazy so even a
            # factory that writes or raises runs only after TaskAttempt has
            # durably entered its intent/effect path. Capture callable
            # references and separate item copies before any earlier runner
            # can mutate caller-owned harness objects.
            runner_item = PlannedItem(
                objective=item.objective,
                role=item.role,
                paths=item.paths,
                gate_paths=item.gate_paths,
                runtime_id=item.runtime_id,
            )
            gate_item = PlannedItem(
                objective=item.objective,
                role=item.role,
                paths=item.paths,
                gate_paths=item.gate_paths,
                runtime_id=item.runtime_id,
            )

            def lazy_runner(
                ctx,
                *,
                factory=runner_factory,
                planned_item=runner_item,
                task_template=callback_task_template,
            ):
                runner = factory(planned_item)
                if not callable(runner):
                    raise TypeError("runner_factory returned a non-callable")
                return runner(_snapshot_callback_context(ctx, task_template))

            def lazy_gate(
                ctx,
                *,
                factory=gate_factory,
                planned_item=gate_item,
                task_template=callback_task_template,
            ):
                gate = factory(planned_item)
                if not callable(gate):
                    raise TypeError("gate_factory returned a non-callable")
                return gate(_snapshot_callback_context(ctx, task_template))

            attempt = TaskAttempt(
                spec,
                runner=lazy_runner,
                gate=lazy_gate,
                repo_root=execution_root,
                ledger_path=run_dir / "spine.sqlite3",
                artifact_dir=run_dir / "artifacts",
                mission_id=mission_id,
                budget=mission_budget,
                mission_policy_sha256=mission_policy_sha256,
            )
            result = attempt.run()
            result_sink.append(result)
            terminal_status = "landed" if result.ok else "bounced"
            # BuildTask is only the mutable BuildSession projection. A runner
            # may retain and mutate it, so bypass any instance-shadowed method
            # and never read its status back into the retained ledger.
            task_result = dict(result.to_dict())
            task_result["work_item"] = {
                "mission_id": mission_id,
                "work_item_id": task_plan.work_item_id,
            }
            BuildTask.mark(task, terminal_status)
            task.last_result = task_result
            rows[index]["status"] = terminal_status
            rows[index]["attempt_id"] = result.branch
            # Digests, never copies: the ledger row points at the canonical
            # records by hash, exactly the posture the ignition receipt takes.
            contracts = result.contract_set()
            rows[index]["attempt_receipt_sha256"] = getattr(
                getattr(contracts, "receipt", None), "digest", None
            )
            rows[index]["evidence_packet_sha256"] = getattr(
                getattr(contracts, "evidence", None), "digest", None
            )
            if not result.ok:
                rows[index]["detail"] = f"state={result.state} error={result.error}"
                outcome = "bounced"
            ledger.publish(base)

        base["outcome"] = outcome
        final = ledger.publish(base)
        return final


__all__ = [
    "LEDGER_SCHEMA",
    "MissionSupervisor",
    "PlannedItem",
    "RoleHarness",
    "StateLedger",
    "StateLedgerBroken",
    "SupervisorRefused",
    "plan_mission",
    "verify_state_ledger",
]
